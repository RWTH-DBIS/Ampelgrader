"""A command that is run to notify students of finished grading processes."""
from django.core.management.base import BaseCommand, CommandError
from django.core.mail import get_connection, send_mail
from django.conf import settings
from grader.models import GradingProcess


FROM_MAIL = "dbis-vl@dbis.rwth-aachen.de"


class Command(BaseCommand):
    help = 'Flush emails to students to notify them of finished grading processes'

    def handle(self, *args, **options):
        # get all students who has not been notified yet
        # use raw functionality, since i am to lazy to look up how to do row locking in django
        unnotified_processes = GradingProcess.objects.raw(f"SELECT * FROM gradingprocess WHERE notified = false FOR UPDATE SKIP LOCKED;")
        
        for process in unnotified_processes:
            try:
                send_mail(
                        "DBIS VL Autograder result is available",
                        f"Hello, the result of your requested grading is available here: {settings.RESULT_LINK_PREFIX}{process.identifier}",
                        FROM_MAIL,
                        [process.email]
                        )
            except Exception as e:
                # to error handling?
                self.stderr.write("Error while sending email:" + str(e))
            else:
                self.stdout.write(f"Notified {process.email}\n") 
                process.notified = True
                process.save()


