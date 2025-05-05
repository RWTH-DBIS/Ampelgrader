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
import asyncio
import asyncpg
import os
from datetime import timedelta

from pgqueuer.qm import QueueManager
from pgqueuer.db import AsyncpgDriver
from pgqueuer.models import Job
from pgqueuer.db import AsyncpgDriver
from pgqueuer.executors import JobExecutor
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
        asyncio.run(grade_studentnotebook())

class GradingExecutor(JobExecutor):
    def __init__(
        self,
        func,
        requests_per_second: float = 2.0,
        retry_timer: timedelta = timedelta(seconds=30),
        serialized_dispatch: bool = True,
        concurrency_limit: int = 5,
    ):
        super().__init__(func, requests_per_second, retry_timer, serialized_dispatch, concurrency_limit)

    async def execute(self, job: Job) -> None:
                
        # Extract notification type and message from job data
        process_id = job.payload.decode()

        await self.grade_notebook(process_id)

    async def grade_notebook(self, process_id) -> None:
        try:
            connection = await asyncpg.connect(
                host=os.getenv("POSTGRES_HOST"),
                database=os.getenv("POSTGRES_DB"),
                user=os.getenv("POSTGRES_USER"),
                password=os.getenv("POSTGRES_PASSWORD")
            )

            driver = AsyncpgDriver(connection)
            # Create a QueueManager instance
            qm = QueueManager(driver)

            try: 
                logger.info("Fetching student notebook")
                s_notebook = await connection.fetchrow("""
                    SELECT * FROM
                    studentnotebook WHERE process = $1; 
                    """,
                    process_id
                )

                notebook_filename = s_notebook["notebook"]
                notebook_data = s_notebook["data"]

            except Exception as e:
                logger.info("Error while fetching notebook:" + str(e))

                await connection.execute("""
                INSERT INTO errorlog (process, log) VALUES($1, $2);
                """,
                    process_id, "Error while fetching notebook: " + str(e)
                )

            try:
                logger.info("Fetching grading process")
                grading_process = await connection.fetchrow("""SELECT * FROM gradingprocess WHERE identifier = $1;""", str(process_id))
                await connection.execute("""
                        INSERT INTO workerassignment (worker_id, process, assigned_at) VALUES($1, $2, $3);
                        """,
                        str(WORKER_ID), str(process_id), datetime.datetime.now()
                        )
                
            except Exception as e:
                logger.info("Error while fetching grading process and store workerassignment:" + str(e))
                if grading_process is None:
                    logger.info(f"Process with ID {process_id} not found.")
                    return

            try:
                result = await grade(
                    {notebook_filename: notebook_data},
                    grading_process["for_exercise"],
                    process_id,
                )
                logger.info(f"Achieved result: {str(result)}")

            except RuntimeError as err:
                logger.error("Grading error!")
                await connection.execute("""
                    INSERT INTO errorlog (process,log) VALUES($1, $2);
                    """,
                        process_id, f"Error through grading: {str(err)}"
                    )
                await enqueue_graded(process_id)
            else:
                notebook_filename = s_notebook["notebook"]
                params = (
                    (
                        process_id,
                        result[cell_id],
                        grading_process["for_exercise"],
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
                await connection.executemany("""
                    INSERT INTO grading (process, cell, points)
                        SELECT $1, cell.id, $2 FROM cell
                            JOIN subexercise ON cell.sub_exercise = subexercise.id
                            JOIN notebook ON subexercise.in_notebook = notebook.filename
                            JOIN exercise ON notebook.in_exercise = exercise.identifier
                        WHERE exercise.identifier = $3
                            AND notebook.filename = $4
                            AND cell.cell_id = $5;
                """, params)

                await qm.queries.enqueue(
                    ["send_email"],
                    [str(process_id).encode()],
                )
            
        except Exception as e:
        # to error handling?
            logger.info("Error while grading notebook:" + str(e))
        else:
            logger.info(f"Grading process with ID {grading_process['identifier']} finished.")
        finally:
            await connection.close()
            logger.info("Connection closed")

class NotebookExecutor(JobExecutor):
    def __init__(
        self,
        func,
        requests_per_second: float = 2.0,
        retry_timer: timedelta = timedelta(seconds=30),
        serialized_dispatch: bool = True,
        concurrency_limit: int = 5,
    ):
        super().__init__(func, requests_per_second, retry_timer, serialized_dispatch, concurrency_limit)

    async def execute(self, job: Job) -> None:
                
        # Extract notification type and message from job data
        notebook_name = job.payload.decode()

        await self.update_notebook(notebook_name)

    async def update_notebook(self, notebook_name) -> None:
        try:
            connection = await asyncpg.connect(
                host=os.getenv("POSTGRES_HOST"),
                database=os.getenv("POSTGRES_DB"),
                user=os.getenv("POSTGRES_USER"),
                password=os.getenv("POSTGRES_PASSWORD")
            )

            try:
                # Retreive notebook from the database
                notebook = await connection.fetchrow("""
                    SELECT * FROM notebook WHERE filename = $1;
                    """,
                    notebook_name
                )

                folder_name = notebook['in_exercise']

                # Store notebook into course directory
                SOURCE_PATH = pathlib.Path(COURSE_DIRECTORY) / pathlib.Path(
                    API.coursedir.source_directory
                )

                # create directory if not exist
                if not os.path.exists(f"{SOURCE_PATH}/{folder_name}"):
                    os.makedirs(f"{SOURCE_PATH}/{folder_name}")
                    logger.info(f"Directory {SOURCE_PATH}/{folder_name} created")

                with open(f"{SOURCE_PATH}/{folder_name}/{notebook_name}", "wb") as f:
                    f.write(notebook['data'])
                    logger.info(f"Notebook {notebook_name} stored in {SOURCE_PATH}/{folder_name}")

                # if assets are present, store them as well
                if notebook['assets'] is not None:
                    with open(f"{SOURCE_PATH}/{folder_name}/assets.zip", "wb") as f:
                        f.write(notebook['assets'])
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
                except:
                    logger.error(f"Error while generating assignment {folder_name}")
                    raise RuntimeError(f"Error while generating assignment {folder_name}")
                else:
                    logger.info(f"Assignment {folder_name} generated")

                    date_now = datetime.datetime.now()

                    # update last_updated field in exercise table
                    await connection.execute("""
                            UPDATE exercise SET last_updated = $1 WHERE identifier = $2;
                        """,
                        date_now, folder_name
                    )

            except Exception as e:
                logger.error("Error while checking if assignment exists:" + str(e))
        except Exception as e:
        # to error handling?
            logger.info("Error while updating notebook:" + str(e))
        else:
            logger.info(f"Notebook {notebook_name} has been updated.")
        finally:
            await connection.close()
            logger.info("Connection closed")
    
async def grade(
    notebook: typing.Dict[str, bytes], assignment: str, id: str
) -> typing.Dict[str, str]:
    """
    Return: Dict with points for each cell in the notebook
    Raises an exception if something goes wrong
    """
    logging.info("Received assignment to grade")

    await check_assignment(assignment)

    # dump the notebook
    dump_notebook(notebook, assignment)

    # start grading
    logger.info(f"Start grading for assignment {assignment}")
    # force: grade even if it is already autograded
    # create: create new student in the database if not already exist
    grading_result = API.autograde(
        assignment, DUMMY_STUDENT_ID, force=True, create=True
    )
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

# https://pgqueuer.readthedocs.io/en/latest/ for the QueueManager
async def grade_studentnotebook():
    """
    Main function to grade the student notebook and update new notebooks.
    """
    connection = await asyncpg.connect(
        host=os.getenv("POSTGRES_HOST"),
        database=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD")
    )

    driver = AsyncpgDriver(connection)
    qm = QueueManager(driver)

    @qm.entrypoint("grade_notebook", executor=GradingExecutor)
    async def grading_task(job: Job) -> None:
        logger.info(f"Executing grading job with ID: {job.id}")

    @qm.entrypoint("update_notebook", executor=NotebookExecutor)
    async def update_task(job: Job) -> None:
        logger.info(f"Executing update job with ID: {job.id}")
    await qm.run()    

# Enqueue the successful graded assignment to the database for further processing
async def enqueue_graded(process_id) -> None:
    # Establish a database connection; asyncpg and psycopg are supported.
    connection = await asyncpg.connect(            
            host=os.getenv("POSTGRES_HOST"),  # Replace with your host
            database=os.getenv("POSTGRES_DB"),  # Replace with your database name
            user=os.getenv("POSTGRES_USER"),  # Replace with your username
            password=os.getenv("POSTGRES_PASSWORD")  # Replace with your password)
    )
    # Initialize a database driver
    driver = AsyncpgDriver(connection)
    # Create a QueueManager instance
    qm = QueueManager(driver)
    await qm.queries.enqueue(
        ["send_email"],
        [str(process_id).encode()],
    )


async def check_assignment(assignment: str) -> None:
    """
    Sanity checking if the assignment exists and is the newest version in the source folder.
    If not, the assignment will be updated.
    """
    try:
        connection = await asyncpg.connect(
            host=os.getenv("POSTGRES_HOST"),
            database=os.getenv("POSTGRES_DB"),
            user=os.getenv("POSTGRES_USER"),
            password=os.getenv("POSTGRES_PASSWORD")
    )
        # check if the assignment exists
        if API.get_assignment(assignment, released=[assignment]) is None:
            # seems to return None if assignment does not exist: https://nbgrader.readthedocs.io/en/stable/_modules/nbgrader/apps/api.html#NbGraderAPI.get_assignment
            logger.error(
                f"Grading for Assignment {assignment} was requested but assignment was not found!"
            )

            # check if there is a notebook for the assignment in the database
            notebook = await connection.fetchrow("""
                    SELECT * FROM notebook WHERE in_exercise=$1;
                """,
                assignment
            )

            if notebook is None:
                logger.error(
                    f"Notebook for assignment {assignment} was not found in the database!"
                )
                raise RuntimeError('Assignment for grading not found')
            else:
                await update_notebook(notebook)
                logger.info(f"Notebook for assignment {assignment} updated") 

        # check if assignment also exist in release folder
        elif not os.path.exists(f"{COURSE_DIRECTORY}/{API.coursedir.release_directory}/{assignment}"):
            logger.error(
                f"Grading for Assignment {assignment} was requested but assignment was not found in release folder!"
            )
            API.generate_assignment(assignment)

        # ensure each worker is uptodate with the newest assignment version, therefore check time of last update in directory
        RELEASE_PATH = pathlib.Path(COURSE_DIRECTORY) / pathlib.Path(
            API.coursedir.release_directory
        )

        last_release_update = datetime.datetime.fromtimestamp(os.path.getmtime(f"{RELEASE_PATH}/{assignment}"), tz=datetime.timezone.utc)
        logger.info(f"Last release updated at: {last_release_update}")

        last_notebook_v = await connection.fetchrow("""
            SELECT * FROM notebook WHERE in_exercise = $1 ORDER BY uploaded_at DESC LIMIT 1;
            """,
            assignment
        )

        logger.info(f"Last notebook version: {last_notebook_v['uploaded_at']}")

        if last_notebook_v['uploaded_at'] > last_release_update :
            logger.info(last_notebook_v['filename'] )
            await update_notebook(last_notebook_v)
            logger.info(f"Notebook for assignment {assignment} updated")
        else: 
            logger.info(f"Notebook for assignment {assignment} is the newest version")
            
    except Exception as e:
        logger.error(f"Error while checking notebook version: {str(e)}")
        raise RuntimeError('Error while checking notebook version')
    else:
        logger.info(f"Notebook is the newest version")
    finally:
        await connection.close()
        logger.info("Connection closed")
    
    return

async def update_notebook(notebook) -> None:
    notebook_name = notebook['filename']
    folder_name = notebook['in_exercise']

    # Store notebook into course directory
    SOURCE_PATH = pathlib.Path(COURSE_DIRECTORY) / pathlib.Path(
        API.coursedir.source_directory
    )

    # create directory if not exist
    if not os.path.exists(f"{SOURCE_PATH}/{folder_name}"):
        os.makedirs(f"{SOURCE_PATH}/{folder_name}")
        logger.info(f"Directory {SOURCE_PATH}/{folder_name} created")

    with open(f"{SOURCE_PATH}/{folder_name}/{notebook_name}", "wb") as f:
        f.write(notebook['data'])
        logger.info(f"Notebook {notebook_name} stored in {SOURCE_PATH}/{folder_name}")
    
    # if assets are present, store them as well
    if notebook['assets'] is not None:
        with open(f"{SOURCE_PATH}/{folder_name}/assets.zip", "wb") as f:
            f.write(notebook['assets'])
            logger.info(f"Notebook assets.zip stored in {SOURCE_PATH}/{folder_name}")
        
        # unzip the assets.zip file
        with ZipFile(f"{SOURCE_PATH}/{folder_name}/assets.zip", "r") as zip_file:
            zip_file.extractall(f"{SOURCE_PATH}/{folder_name}")
            logger.info(f"Notebook assets unzipped in {SOURCE_PATH}/{folder_name}")

        # delete the assets.zip file
        os.remove(f"{SOURCE_PATH}/{folder_name}/assets.zip")

    try:
        # generate the assignment 
        # (store notebook in src dir to release and stripping all output cells)
        # https://nbgrader.readthedocs.io/en/stable/user_guide/what_is_nbgrader.html#nbgrader-generate-assignment
        API.generate_assignment(folder_name)
    except:
        # error handling for multiple workers? 
        logger.error(f"Error while generating assignment {folder_name}")
        raise RuntimeError(f"Error while generating assignment {folder_name}")
    else:
        logger.info(f"Assignment {folder_name} generated")

if __name__ == "__main__":
    cmd()
