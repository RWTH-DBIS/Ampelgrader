"""A command that is run to notify students of finished grading processes."""
from django.core.management.base import BaseCommand
from datetime import timedelta
from django.core.mail import send_mail
from django.conf import settings
import psycopg2, os, asyncio
import logging

# import asyncpg, asyncio, os

MAIL_TEMPLATE = lambda x: f"""Hallo,

Die Ampel-Bewertung ihrer Abgabe ist abgeschlossen.
Das Ergebnis finden Sie hier: {settings.RESULT_LINK_PREFIX}{x}".

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
conn = psycopg2.connect(host=os.getenv("NBBB_DB_HOST", "localhost"), 
                dbname=os.getenv("NBBB_DB_NAME", "grader"), 
                user=os.getenv("NBBB_DB_USER", "user"), 
                password=os.getenv("NBBB_DB_PASSWD", "password"))
conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)

cursor = conn.cursor()
cursor.execute(f"LISTEN notify_student;")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

class Command(BaseCommand):
    # help = 'Flush emails to students to notify them of finished grading processes'
    # asyncio.run(notify_students())

    def handle(self, *args, **options):
        cursor.execute(f"LISTEN notify_student;")

        loop = asyncio.get_event_loop()
        loop.add_reader(conn, self.handle_notify)
        loop.run_forever()

    def handle_notify(self):
        conn.poll()
        for notify in conn.notifies:
            # logger.info("Received notification for process: %s", notify.payload)
            process_id = notify.payload
            self.send_mail_to_student(process_id)
        conn.notifies.clear()

    def send_mail_to_student(self, process_id) -> None:
        try:
            cursor.execute("""SELECT identifier, email FROM gradingprocess WHERE identifier = %s;""", [str(process_id)])
            process = cursor.fetchone()
            
            if not process:
                logger.warning(f"No process found for identifier: {process_id}")
                return
            
            send_mail(
                settings.EMAIL_HEADER,
                settings.MAIL_TEMPLATE_RENDERER(process_id),
                settings.EMAIL_ADDRESS,
                [process[1]],
                html_message=settings.MAIL_TEMPLATE_RENDERER(process_id)
                )
            
        except Exception as e:
        # to error handling?
            logger.error(f"Error sending email for process {process_id}: {e}")
            return
        else:
            try:
              cursor.execute("""
                             UPDATE daily_contingent SET count = count + 1 WHERE user_email = %s; 
                             UPDATE gradingprocess SET notified = true WHERE identifier = %s;""", 
                             [process[1], process[0]]
                             )
            except Exception as e:
                logger.error(f"Error updating tables: {e}")
                return
            logger.info(f"Sent email to {process[1]} for process {process_id}")

