import os
import sys
import typing
from sys import argv
import pika
import logging
import pathlib


from nbgrader.apps import NbGraderAPI
from nbgrader.coursedir import CourseDirectory

from nbblackbox_common import NBBBGradingRequest, NBBBGradingResponse
COURSE_DIRECTORY = os.environ.get("COURSE_DIRECTORY", "/course")
DUMMY_STUDENT_ID="d"

RABBITMQ_HOST = os.environ.get("RABBITMQ_HOST", "localhost")
RABBITMQ_QUEUE = os.environ.get("RABBITMQ_QUEUE", "grading")
RABBITMQ_RSP_QUEUE = os.environ.get("RABBITMQ_RSP_QUEUE", "grading_rsp")

# How to initialise the CourseDirectory is nowhere documented. using the root flag to set the according attribute seems to work
API = NbGraderAPI(coursedir=CourseDirectory(root=str(COURSE_DIRECTORY)))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
def dump_notebook(notebooks: typing.Dict[str, str], for_assignment: str):
    """Dumps the notebook into the submission folder for the given assignment of the dummy student"""
    path = pathlib.Path(COURSE_DIRECTORY) / "submitted" / DUMMY_STUDENT_ID / for_assignment
    # create folder at the path for the assignment, if not exist yet
    path.mkdir(exist_ok=True)
    # create path which specifies where the notebook will be dumped
    for notebook in notebooks.keys():
        sub_path = path / pathlib.Path(notebook)
        logging.info(f"Dumping the notebook into {sub_path}")
        with sub_path.open("w") as f:
            f.write(notebooks[notebook])

def main():
    """Main Loop"""
    logger.info("NBWorker started")
    logger.info(f"Using Course Directory: {API.coursedir.root}")
    con = pika.BlockingConnection(pika.ConnectionParameters(RABBITMQ_HOST))
    channel = con.channel()
    # setup queues to be durable, so they outlive container stop
    channel.queue_declare(queue=RABBITMQ_QUEUE, durable=True)
    channel.queue_declare(queue=RABBITMQ_RSP_QUEUE, durable=True)
    channel.basic_consume(queue=RABBITMQ_QUEUE, on_message_callback=callback)
    # do not allow prefetching of any messages
    channel.basic_qos(prefetch_count=1)

    logger.info("Waiting for assignments to grade...")
    channel.start_consuming()


def unsuccessful_grading(ch, method, id):
    """
    Send Back a NBBGradingAnswer via the globally defined channel containing with successful=false
    and an empty grading dict.
    """
    # send response that grading was not successful
    gqr = NBBBGradingResponse(id, False, {})
    # send directly to response queue, mark as persistent
    ch.basic_publish(exchange='',
                     routing_key=RABBITMQ_RSP_QUEUE,
                     body=gqr.dump(),
                     properties=pika.BasicProperties(
                         delivery_mode=pika.DeliveryMode.Persistent
                     ))
    # acknowledge so that the request is not sent to other worker
    ch.basic_ack(delivery_tag=method.delivery_tag)

def callback(ch, method, properties, body):
    logging.info("Received assignment to grade")

    gq = NBBBGradingRequest.load(body)

    # Delete any old submission present
    # ...do we just delete the file in the submitted folder or do we access the notebook via Gradebook?
    # also check if the assignment exist
    # overwrite released so there is no database request whether the release of the assignment was generated
    if API.get_assignment(gq.assignment, released=[gq.assignment]) is None:
        # seems to return None if assignment does not exist: https://nbgrader.readthedocs.io/en/stable/_modules/nbgrader/apps/api.html#NbGraderAPI.get_assignment
        logger.error(f"Grading for Assignment {gq.assignment} was requested but assignment was not found!")
        unsuccessful_grading(ch, method, gq.id)
        return


    # dump the notebook
    dump_notebook(gq.notebook, gq.assignment)

    # start grading
    logger.info(f"Start grading for assignment {gq.assignment}")
    # force: grade even if it is already autograded
    # create: create new student in the database if not already exist
    grading_result = API.autograde(gq.assignment, DUMMY_STUDENT_ID, force=True, create=True)
    if not grading_result["success"]:
       logger.error(f"Grading error: {grading_result['error']}")
       logger.error(f"Log of Notebook:{str(grading_result['log'])}")
       unsuccessful_grading(ch, method, gq.id)
       return
    else:
        logger.info(f"Finished grading")

    cell_point_dict = {}

    with API.gradebook as g:
        # retrieve the submission from the database
        sb = g.find_submission(gq.assignment, DUMMY_STUDENT_ID)
        # we assume only one notebook, therefore just take the first one
        nb = sb.notebooks[0]
        for gr in nb.grades:
            cell_point_dict[gr.cell_id] = gr.auto_score
        logger.info(f"Notebook achieved {nb.score}/{nb.max_score}")

    # send back positive response
    gqr = NBBBGradingResponse(gq.id, True, cell_point_dict)
    # send directly to response queue, mark as persistent
    ch.basic_publish(exchange='',
                     routing_key=RABBITMQ_RSP_QUEUE,
                     body=gqr.dump(),
                     properties=pika.BasicProperties(
                         delivery_mode=pika.DeliveryMode.Persistent
                     ))
    # acknowledge so that the request is not sent to other worker
    ch.basic_ack(delivery_tag=method.delivery_tag)


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
