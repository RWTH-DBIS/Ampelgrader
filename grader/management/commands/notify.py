"""A command that is run to notify students of finished grading processes."""
from django.core.management.base import BaseCommand, CommandError
from django.core.mail import get_connection, send_mail
from django.conf import settings
from grader.models import GradingProcess


FROM_MAIL = "dbis-vl@dbis.rwth-aachen.de"

MAIL_TEMPLATE = lambda x: f"""Hallo,

Die Ampel-Bewertung ihrer Abgabe ist abgeschlossen.
Das Ergebniss finden Sie hier: {settings.RESULT_LINK_PREFIX}{x}".

Viele Grüße,

Das DBIS-VL Team

-------------
Diese Email ist autogeneriert. Bitte antworten Sie nicht auf diese E-Mail. Bei Fragen wenden Sie sich bitte an dbis-ticket@dbis.rwth-aachen.de.
"""


HTML_MAIL_TEMPLATE = lambda x: f"""
<p>Hallo,</p>
<br>
<p>Die Ampel-Bewertung ihrer Abgabe ist abgeschlossen.</p>
<p>Das Ergebniss finden Sie <a href="{settings.RESULT_LINK_PREFIX}{x}">hier</a>.</p>
<br>
<p>Viele Grüße,</p>
<br>
<p>Das DBIS-VL Team</p>
<br>
<br>
<footer style="color: darkgrey; font_size: small;">Diese Email ist autogeneriert. Bitte antworten Sie nicht auf diese E-Mail. Bei Fragen wenden Sie sich bitte an dbis-ticket@dbis.rwth-aachen.de.</footer>
"""

class Command(BaseCommand):
    help = 'Flush emails to students to notify them of finished grading processes'

    def handle(self, *args, **options):
        # get all students who has not been notified yet
        # use raw functionality, since i am to lazy to look up how to do row locking in django
        unnotified_processes = GradingProcess.objects.raw(f"SELECT * FROM gradingprocess WHERE notified = false FOR UPDATE SKIP LOCKED;")
        
        for process in unnotified_processes:
            try:
                send_mail(
                        "DBIS VL Autograder Bewertung abgeschlossen",
                        MAIL_TEMPLATE(process.identifier),
                        FROM_MAIL,
                        [process.email],
                        html_message=HTML_MAIL_TEMPLATE(process.identifier)
                        )
            except Exception as e:
                # to error handling?
                self.stderr.write("Error while sending email:" + str(e))
            else:
                self.stdout.write(f"Notified {process.email}\n") 
                process.notified = True
                process.save()


