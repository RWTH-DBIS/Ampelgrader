import os
import sys
import typing
from sys import argv
import logging
import pathlib
import psycopg2
import psycopg2.extras
import uuid
import datetime
import signal
import asyncio

from zipfile import ZipFile

from nbgrader.apps import NbGraderAPI
from nbgrader.coursedir import CourseDirectory

POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.environ.get("POSTGRES_PORT", 5432)
POSTGRES_USER = os.environ.get("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "")
POSTGRES_DB = os.environ.get("POSTGRES_DB", "")
# For models see the models.py in the grader app
# There, we especially force django to set the field and database name


WAITING_TIME = int(os.environ.get("WAITING_TIME", "5"))
"""The time waited in seconds between database access to check for pending jobs"""
COURSE_DIRECTORY = os.environ.get("COURSE_DIRECTORY", "/course")
DUMMY_STUDENT_ID = "d"
"""A dummy student id, the only student in this system. THeir submissions is always overwritten with each new grading job"""


WORKER_ID = uuid.uuid4()

# https://stackoverflow.com/questions/51105100/psycopg2-cant-adapt-type-uuid
psycopg2.extras.register_uuid()

# How to initialise the CourseDirectory is nowhere documented. using the root flag to set the according attribute seems to work
API = NbGraderAPI(coursedir=CourseDirectory(root=str(COURSE_DIRECTORY)))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

conn = psycopg2.connect(host=POSTGRES_HOST, 
                dbname=POSTGRES_DB, 
                user=POSTGRES_USER, 
                password=POSTGRES_PASSWORD)
conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
cursor = conn.cursor()

def dump_notebook(notebooks: typing.Dict[str, bytes], for_assignment: str):
    """Dumps the notebook into the submission folder for the given assignment of the dummy student"""
    path = (
        pathlib.Path(COURSE_DIRECTORY) / "submitted" / DUMMY_STUDENT_ID / for_assignment
    )
    # create folder at the path for the assignment, if not exist yet
    path.mkdir(exist_ok=True)
    # create path which specifies where the notebook will be dumped
    for notebook in notebooks.keys():
        sub_path = path / pathlib.Path(notebook)
        logging.info(f"Dumping the notebook into {sub_path}")
        with sub_path.open("wb") as f:
            f.write(notebooks[notebook])

   
def grade(
    notebook: typing.Dict[str, bytes], assignment: str, id: str
) -> typing.Dict[str, str]:
    """
    Return: Dict with points for each cell in the notebook
    Raises an exception if something goes wrong
    """
    logging.info("Received assignment to grade")

    check_assignment(assignment)

    # dump the notebook
    dump_notebook(notebook, assignment)

    # start grading
    logger.info(f"Start grading for assignment {assignment}")
    # force: grade even if it is already autograded
    # create: create new student in the database if not already exist
    try: 
      grading_result = API.autograde(
          assignment, DUMMY_STUDENT_ID, force=True, create=True
      )
    except RuntimeError as e:
        logger.error(f"Error while grading notebook: {str(e)}")
        raise RuntimeError(f"Error while grading notebook: {str(e)}")
    
    if not grading_result["success"]:
        logger.error(f"Grading error: {grading_result['error']}")
        logger.error(f"Log of Notebook:{str(grading_result['log'])}")
        raise RuntimeError(f"Grading failed:{str(grading_result['error'])}")
    else:
        logger.info(f"Finished grading")

    cell_point_dict = {}

    with API.gradebook as g:
        # retrieve the submission from the database
        sb = g.find_submission(assignment, DUMMY_STUDENT_ID)
        # we assume only one notebook, therefore just take the first one
        nb = sb.notebooks[0]
        for gr in nb.grades:
            # the name corrosponds to the field "grade_id" in the
            # nbgrader metadata in the cell
            # this is the only thing accessible
            # cell.id is a database pk without any real world connections
            cell_point_dict[gr.cell.name] = gr.auto_score
        logger.info(f"Notebook achieved {nb.score}/{nb.max_score}")

    return cell_point_dict

# Enqueue the successful graded assignment to the database for further processing
def enqueue_graded(process_id) -> None:
    logger.info(f"Enqueuing graded notebook with process id {process_id} to notify the student.")
    cursor.execute(f"NOTIFY notify_student, '{process_id}';")

def grade_notebook(process_id) -> None:
    try:
        try: 
            logger.info(f"Fetching student notebook with process id {process_id}")
            cursor.execute(
              """
              SELECT data, notebook FROM
              studentnotebook WHERE process = %s; 
              """,
                  [process_id],
              )
            if cursor.rowcount == 0:
                # we shouldnt be here
                cursor.execute(
                """
                INSERT INTO errorlog(process, log) VALUES(%s,%s);
                """,
                    [process_id, "No uploaded notebook found"],
                )
                conn.commit()
            (notebook_data, notebook_filename) = cursor.fetchone()

        except Exception as e:
            logger.info("Error while fetching notebook:" + str(e))

            cursor.execute(
            """
              INSERT INTO errorlog(process, log) VALUES(%s,%s);
            """,
                [process_id, "No uploaded notebook found"],
            )

        try:
            # logger.info("Fetching grading process")
            cursor.execute(
            """
            SELECT gradingprocess.identifier, gradingprocess.requested_at, gradingprocess.for_exercise FROM gradingprocess WHERE identifier = %s;
            """,
              [process_id],
            )

            grading_process = cursor.fetchone()

            # logger.info(f"Grading process: {grading_process}")

            cursor.execute(
            """
            INSERT INTO workerassignment (worker_id, process, assigned_at)
                VALUES(%s,%s,%s);
            """,
              [WORKER_ID, process_id, datetime.datetime.now()],
            )
            logger.info(f"Worker assignment for process {process_id} created.")

        except Exception as e:
            logger.info("Error while fetching grading process and store workerassignment:" + str(e))
            cursor.execute(
            """
              INSERT INTO errorlog(process, log) VALUES(%s,%s);
            """,
                [process_id, "Error while fetching grading process" + str(e)],
            )
            if grading_process is None:
                logger.info(f"Process with ID {process_id} not found.")
                return

        try:
            logger.info("Starting grading process...")
            result = grade(
                {notebook_filename: notebook_data.tobytes()},
                grading_process[2],
                process_id,
            )

            logger.info(f"Achieved result: {str(result)}")

        except RuntimeError as err:
            logger.error("Grading error!")
            cursor.execute(
            """
            INSERT INTO errorlog(process,log) VALUES(%s,%s);
            """,
            [process_id, f"Error through grading: {str(err)}"],
            )

            enqueue_graded(process_id)
        else:
            
            params = (
                (
                    process_id,
                    result[cell_id],
                    grading_process[2],
                    notebook_filename,
                    cell_id,
                )
                for cell_id in result.keys()
            )
            logger.info("Inserting result into the database...")
            # We need the correct pk of the cell, as grading has a foreign key on the pk
            # of the cell, NOT ON THE CELL_ID AS IN THE NOTEBOOK
            # for this we join the cell on subexercise on notebook on exercise
            # and compare the cell_id in the cell table which holds the cell id as in the
            # notebook
            psycopg2.extras.execute_batch(
                cursor,
                """
            INSERT INTO grading(process,cell,points)
                SELECT %s, cell.id, %s FROM cell 
                    JOIN subexercise ON cell.sub_exercise=subexercise.id
                    JOIN notebook ON subexercise.in_notebook=notebook.filename
                    JOIN exercise ON notebook.in_exercise=exercise.identifier
                WHERE exercise.identifier=%s
                    AND notebook.filename=%s
                    AND cell.cell_id=%s
            """,
                params,
            )

            enqueue_graded(process_id)
            
    except Exception as e:
    # to error handling?
        logger.info("Error while grading notebook:" + str(e))
        cursor.execute(
        """
          INSERT INTO errorlog(process, log) VALUES(%s,%s);
        """,
            [process_id, "Error while grading notebook: " + str(e)],
        )
    else:
        logger.info(f"Grading process with ID {grading_process[0]} finished.")

def check_assignment(assignment: str) -> None:
    """
    Sanity checking if the assignment exists and is the newest version in the source folder.
    If not, the assignment will be updated.
    """
    try:
        # check if the assignment exists
        if API.get_assignment(assignment, released=[assignment]) is None:
            # seems to return None if assignment does not exist: https://nbgrader.readthedocs.io/en/stable/_modules/nbgrader/apps/api.html#NbGraderAPI.get_assignment
            logger.error(
                f"Grading for Assignment {assignment} was requested but assignment was not found!"
            )
            cursor.execute("""
                    SELECT * FROM notebook WHERE in_exercise=%s;
                """,
                [assignment]
            )
            # check if there is a notebook for the assignment in the database
            notebook = cursor.fetchone()

            if notebook is None:
                logger.error(
                    f"Notebook for assignment {assignment} was not found in the database!"
                )
                raise RuntimeError('Assignment for grading not found')
            else:
                update_notebook(notebook[0])
                logger.info(f"Notebook for assignment {assignment} updated") 

        # check if assignment also exist in release folder
        elif not os.path.exists(f"{COURSE_DIRECTORY}/{API.coursedir.release_directory}/{assignment}"):
            logger.error(
                f"Grading for Assignment {assignment} was requested but assignment was not found in release folder!"
            )
            API.generate_assignment(assignment)
            # logger.info(f"Assignment {assignment} generated in release folder")

        # ensure each worker is uptodate with the newest assignment version, therefore check time of last update in directory
        RELEASE_PATH = pathlib.Path(COURSE_DIRECTORY) / pathlib.Path(
            API.coursedir.release_directory
        )

        last_release_update = datetime.datetime.fromtimestamp(os.path.getmtime(f"{RELEASE_PATH}/{assignment}"), tz=datetime.timezone.utc)
        # logger.info(f"Last release updated at: {last_release_update}")

        cursor.execute("""
            SELECT * FROM notebook WHERE in_exercise = %s ORDER BY uploaded_at DESC LIMIT 1;
            """,
            [assignment]
        )

        last_notebook_v = cursor.fetchone()

        # logger.info(f"Last notebook version: {last_notebook_v[3]}")

        if last_notebook_v[3] > last_release_update :
            logger.info(last_notebook_v[0])
            update_notebook(last_notebook_v[0])
            logger.info(f"Notebook for assignment {assignment} updated")
        else: 
            logger.info(f"Notebook for assignment {assignment} is the newest version")
            
    except Exception as e:
        logger.error(f"Error while checking notebook version: {str(e)}")
        raise RuntimeError('Error while checking notebook version')
    else:
        logger.info(f"Notebook is the newest version")

    return

def store_release_data(notebook_name: str, release_data: bytes) -> None:
    """
    Store the release data of a notebook in the database.
    """
    try:
        cursor.execute("""
            UPDATE notebook SET release_data = %s WHERE filename = %s;
            """,
            [release_data, notebook_name]
        )
        conn.commit()
        logger.info(f"Release data for notebook {notebook_name} stored in database")
    except Exception as e:
        logger.error(f"Error while storing release data for notebook {notebook_name}: {str(e)}")
        raise RuntimeError(f"Error while storing release data for notebook {notebook_name}")

def update_notebook(notebook_name) -> None:
    try:
        try:
            # Retreive the last updated notebook from the database
            cursor.execute("""
                SELECT * FROM notebook WHERE filename = %s ORDER BY uploaded_at DESC LIMIT 1;
                """,
                [notebook_name]
            )

            notebook = cursor.fetchone()
            
            folder_name = notebook[1]

            RELEASE_PATH = pathlib.Path(COURSE_DIRECTORY) / pathlib.Path(
                API.coursedir.release_directory
            )

            # Store notebook into course directory
            SOURCE_PATH = pathlib.Path(COURSE_DIRECTORY) / pathlib.Path(
                API.coursedir.source_directory
            )

            # create directory if not exist
            if not os.path.exists(f"{SOURCE_PATH}/{folder_name}"):
                os.makedirs(f"{SOURCE_PATH}/{folder_name}")
                logger.info(f"Directory {SOURCE_PATH}/{folder_name} created")

            with open(f"{SOURCE_PATH}/{folder_name}/{notebook_name}", "wb") as f:
                f.write(notebook[2])
                logger.info(f"Notebook {notebook_name} stored in {SOURCE_PATH}/{folder_name}")

            # if assets are present, store them as well
            if notebook[4] is not None:
                with open(f"{SOURCE_PATH}/{folder_name}/assets.zip", "wb") as f:
                    f.write(notebook[4])
                    logger.info(f"Notebook assets.zip stored in {SOURCE_PATH}/{folder_name}")
                
                # unzip the assets.zip file
                with ZipFile(f"{SOURCE_PATH}/{folder_name}/assets.zip", "r") as zip_file:
                    zip_file.extractall(f"{SOURCE_PATH}/{folder_name}")
                    logger.info(f"Notebook assets unzipped in {SOURCE_PATH}/{folder_name}")
        
                os.remove(f"{SOURCE_PATH}/{folder_name}/assets.zip")
                
            try:
                # generate the assignment 
                # (store notebook in src dir to release and stripping all output cells)
                # https://nbgrader.readthedocs.io/en/stable/user_guide/what_is_nbgrader.html#nbgrader-generate-assignment
                API.generate_assignment(folder_name)

                release_notebook = API.get_assignment(folder_name, released=[folder_name])
                if release_notebook is None:
                    logger.error(f"Assignment {folder_name} could not be generated")
                    raise RuntimeError(f"Assignment {folder_name} could not be generated")
                else:
                    data = _file_to_bytes(f"{RELEASE_PATH}/{folder_name}/{notebook_name}")
                    store_release_data(notebook_name, data)
                    logger.info(f"Release data for assignment {folder_name} stored in database")

            except:
                logger.error(f"Error while generating assignment {folder_name}")
                raise RuntimeError(f"Error while generating assignment {folder_name}")
            else:
                logger.info(f"Assignment {folder_name} generated")

                date_now = datetime.datetime.now()

                # update last_updated field in exercise table
                cursor.execute("""
                        UPDATE exercise SET last_updated = %s WHERE identifier = %s;
                    """,
                    [date_now, folder_name]
                )

        except Exception as e:
            logger.error("Error while checking if assignment exists:" + str(e))
    except Exception as e:
    # to error handling?
        logger.info("Error while updating notebook:" + str(e))
    else:
        logger.info(f"Notebook {notebook_name} has been updated.")

def _file_to_bytes(file_path: str) -> bytes:
    """
    Reads a file and returns its content as bytes.
    """
    with open(file_path, "rb") as f:
        return f.read()

def handle_listener():
    conn.poll()
    while conn.notifies:
        notify = conn.notifies.pop(0)
        logger.info(f"Received notification: {notify.channel} - {notify.payload}")
        if notify.channel == "update_notebook":
            filename = notify.payload
            update_notebook(filename)
        elif notify.channel == "grade_notebook":
            process_id = notify.payload
            grade_notebook(process_id)
        else:
            logger.warning(f"Unknown notification channel: {notify.channel}")
        conn.notifies.clear()

def main():
    """Main Loop"""
    logger.info(f"NBWorker started with worker id {WORKER_ID}")
    logger.info(f"Using Course Directory: {API.coursedir.root}")

    # register a kill method
    class Killswitch:
        """A small class which is used for signal handling and termination of the main loop"""

        def __init__(self):
            self.running = True

        def kill(self, *kwargs):
            logger.info("Received term signal. Exiting...")
            self.running = False

    k = Killswitch()
    signal.signal(signal.SIGINT, k.kill)
    signal.signal(signal.SIGTERM, k.kill)
    while k.running:
        cursor.execute(f"LISTEN update_notebook;")
        cursor.execute(f"LISTEN grade_notebook;")

        loop = asyncio.get_event_loop()
        loop.add_reader(conn, handle_listener)
        loop.run_forever()

def cmd():
    GRADEBOOK = API.gradebook
    # check if the dummy student exists and if not, create it
    GRADEBOOK.update_or_create_student(DUMMY_STUDENT_ID)
    GRADEBOOK.close()
    # create the folder if not exist with all parents
    PATH = pathlib.Path(COURSE_DIRECTORY) / "submitted" / DUMMY_STUDENT_ID
    PATH.mkdir(parents=True, exist_ok=True)
    # nbgrader will not work if the assignments are not in the database
    # it seems to be necessary to generate the assignments, so that nbgrader is correctly initialised
    # therefore we do that for every assignment present
    SOURCE_PATH = pathlib.Path(COURSE_DIRECTORY) / pathlib.Path(
        API.coursedir.source_directory
    )

    try:
        main()
    except KeyboardInterrupt:
        try:
            conn.close()
            sys.exit(0)
        except SystemExit:
            conn.close()
            os._exit(0)

if __name__ == "__main__":
    cmd()
