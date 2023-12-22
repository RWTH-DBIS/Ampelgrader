import os
import sys
import typing
from sys import argv
import logging
import pathlib
import psycopg2
import psycopg2.extras
import time
import uuid
import datetime
import signal

from nbgrader.apps import NbGraderAPI
from nbgrader.coursedir import CourseDirectory

POSTGRES_HOST = os.environ.get('POSTGRES_HOST', 'localhost')
POSTGRES_PORT = os.environ.get('POSTGRES_PORT', 5432)
POSTGRES_USER = os.environ.get('POSTGRES_USER', 'postgres')
POSTGRES_PASSWORD = os.environ.get('POSTGRES_PASSWORD', '')
POSTGRES_DB = os.environ.get('POSTGRES_DB', '')

WAITING_TIME = int(os.environ.get('WAITING_TIME', '5'))

COURSE_DIRECTORY = os.environ.get("COURSE_DIRECTORY", "/course")
DUMMY_STUDENT_ID="d"

WORKER_ID = uuid.uuid4()

# https://stackoverflow.com/questions/51105100/psycopg2-cant-adapt-type-uuid
psycopg2.extras.register_uuid()

# How to initialise the CourseDirectory is nowhere documented. using the root flag to set the according attribute seems to work
API = NbGraderAPI(coursedir=CourseDirectory(root=str(COURSE_DIRECTORY)))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
def dump_notebook(notebooks: typing.Dict[str, bytes], for_assignment: str):
    """Dumps the notebook into the submission folder for the given assignment of the dummy student"""
    path = pathlib.Path(COURSE_DIRECTORY) / "submitted" / DUMMY_STUDENT_ID / for_assignment
    # create folder at the path for the assignment, if not exist yet
    path.mkdir(exist_ok=True)
    # create path which specifies where the notebook will be dumped
    for notebook in notebooks.keys():
        sub_path = path / pathlib.Path(notebook)
        logging.info(f"Dumping the notebook into {sub_path}")
        with sub_path.open("wb") as f:
            f.write(notebooks[notebook])

def main():
    """Main Loop"""
    logger.info(f"NBWorker started with worker id {WORKER_ID}")
    logger.info(f"Using Course Directory: {API.coursedir.root}")
    logger.info(f"Connecting to database...")
    conn = psycopg2.connect(host=POSTGRES_HOST, dbname=POSTGRES_DB, user=POSTGRES_USER, password=POSTGRES_PASSWORD, port=POSTGRES_PORT)
    cur = conn.cursor()
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
        time.sleep(WAITING_TIME)
        logger.info("Checking for ungraded assignments...")
        # check if there are free tasks in the form of unhandled grading processes
        cur.execute("""
        SELECT identifier, requested_at, for_exercise FROM gradingprocess WHERE 
            identifier NOT IN (SELECT process FROM errorlog)
            AND identifier NOT IN (SELECT process FROM grading)
            AND identifier NOT IN (SELECT process FROM workerassignment)
            ORDER BY requested_at DESC;
        """)
        if cur.rowcount > 0:
            available_job = cur.fetchone()
            process_id = available_job[0]
            assignment = available_job[2]
            # assign ourselves to the job
            cur.execute("""
            INSERT INTO workerassignment (worker_id, process, assigned_at)
                VALUES(%s,%s,%s);
            """, (WORKER_ID, process_id, datetime.datetime.now()))
            # try committing the transaction
            try:
                conn.commit()
            except psycopg2.Error as err:
                logger.error(f"Database Error: {err}")
            else:
                # commit successful, get necessary info from the db
                # and grade
                # get uploaded notebook
                cur.execute("""
                   SELECT data, notebook FROM
                   studentnotebook WHERE process = %s; 
                """, [process_id])
                if cur.rowcount == 0:
                    # we shouldnt be here
                    cur.execute("""
                    INSERT INTO errolog(process,log) VALUES(%s,%s);
                    """, (process_id, "No uploaded notebook found"))
                    conn.commit()
                    continue
                (notebook_data, notebook_filename) = cur.fetchone()
                try:
                    # psycopg returns a memory view, therefore we convert it to a bytestring via .tobytes()
                    result = grade({notebook_filename: notebook_data.tobytes()}, assignment, process_id)
                    logger.info(f"Achieved result: {str(result)}")
                except RuntimeError as err:
                    logger.error("Grading error!")
                    cur.execute("""
                    INSERT INTO errorlog(process,log) VALUES(%s,%s);
                    """, (process_id, f"Error through grading: {str(err)}"))
                    conn.commit()
                    continue
                else:
                    params = [(process_id, result[cell_id], assignment, notebook_filename, cell_id) for cell_id in result.keys()]
                    # We need the correct pk of the cell, as grading has a foreign key on the pk
                    # of the cell, NOT ON THE CELL_ID AS IN THE NOTEBOOK
                    # for this we join the cell on subexercise on notebook on exercise
                    # and compare the cell_id in the cell table which holds the cell id as in the
                    # notebook
                    cur.executemany("""
                    INSERT INTO grading(process,cell,points)
                        SELECT %s, Cell.id, %s FROM Cell 
                            JOIN subexercise ON cell.id=subexercise.id
                            JOIN notebook ON subexercise.in_notebook=notebook.filename
                            JOIN exercise ON notebook.in_exercise=exercise.identifier
                        WHERE exercise.identifier=%s
                            AND notebook.filename=%s
                            AND cell.cell_id=%s
                    """, params)
        else:
            logger.debug("No job found!")
        conn.commit()
        logger.debug("Waiting...")


def grade(notebook: typing.Dict[str, bytes], assignment: str, id: str) -> typing.Dict[str, str]:
    """
    Return: Dict with points for each cell in the notebook
    Raises an exception if something goes wrong
    """
    logging.info("Received assignment to grade")


    # Delete any old submission present
    # ...do we just delete the file in the submitted folder or do we access the notebook via Gradebook?
    # also check if the assignment exist
    # overwrite released so there is no database request whether the release of the assignment was generated
    if API.get_assignment(assignment, released=[assignment]) is None:
        # seems to return None if assignment does not exist: https://nbgrader.readthedocs.io/en/stable/_modules/nbgrader/apps/api.html#NbGraderAPI.get_assignment
        logger.error(f"Grading for Assignment {assignment} was requested but assignment was not found!")
        raise RuntimeError("Assignment does not exist!")


    # dump the notebook
    dump_notebook(notebook, assignment)

    # start grading
    logger.info(f"Start grading for assignment {assignment}")
    # force: grade even if it is already autograded
    # create: create new student in the database if not already exist
    grading_result = API.autograde(assignment, DUMMY_STUDENT_ID, force=True, create=True)
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


def cmd():
    GRADEBOOK = API.gradebook
    GRADEBOOK.add_student(DUMMY_STUDENT_ID)
    GRADEBOOK.close()
    # create the folder if not exist with all parents
    PATH = pathlib.Path(COURSE_DIRECTORY) / "submitted" / DUMMY_STUDENT_ID
    PATH.mkdir(parents=True, exist_ok=True)
    # nbgrader will not work if the assignments are not in the database
    # it seems to be necessary to generate the assignments, so that nbgrade is correctly initialised
    # therefore we do that for every assignment present
    SOURCE_PATH = pathlib.Path(COURSE_DIRECTORY) / pathlib.Path(API.coursedir.source_directory)
    # we assume every directory is an assignment
    for assi in SOURCE_PATH.iterdir():
        if assi.is_dir():
            logger.info(f"Generate Assignment {assi.name}...")
            API.generate_assignment(assi.name)
    try:
        main()
    except KeyboardInterrupt:
        try:
            sys.exit(0)
        except SystemExit:
            os._exit(0)


if __name__ == "__main__":
    cmd()
