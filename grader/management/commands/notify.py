"""A command that is run to notify students of finished grading processes."""
from django.core.management.base import BaseCommand
from datetime import timedelta
from django.core.mail import send_mail
from django.conf import settings
from pgqueuer.qm import QueueManager
from pgqueuer.models import Job
from pgqueuer.db import AsyncpgDriver
from pgqueuer.executors import JobExecutor
import asyncpg, asyncio, os

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

class Command(BaseCommand):
    # help = 'Flush emails to students to notify them of finished grading processes'
    # asyncio.run(notify_students())
    def handle(self, *args, **options):
        asyncio.run(self.notify_students())

    async def notify_students(self):
        connection = await asyncpg.connect(
            host=os.getenv("NBBB_DB_HOST"),
            database=os.getenv("PG_DATABASE"),
            user=os.getenv("NBBB_DB_USER"),
            password=os.getenv("NBBB_DB_PASSWD")
        )

        driver = AsyncpgDriver(connection)
        qm = QueueManager(driver)

        @qm.entrypoint("send_email", executor=NotificationExecutor)
        async def notification_task(job: Job) -> None:
            print(f"Executing notification job with ID: {job.id}")

        await qm.run()

class NotificationExecutor(JobExecutor):
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
        if settings.EMAIL_ADDRESS is None:
            print("No email adress set. Please set EMAIL_ADRESS in settings.py")
            return
                
        # Extract notification type and message from job data
        process_id = job.payload.decode()

        await self.send_mail_to_student(process_id)

        # Execute the original job function if required
        # await self.func(job)

    async def send_mail_to_student(self, process_id) -> None:
        try:
            connection = await asyncpg.connect(
                host=os.getenv("NBBB_DB_HOST"),
                database=os.getenv("PG_DATABASE"),
                user=os.getenv("NBBB_DB_USER"),
                password=os.getenv("NBBB_DB_PASSWD")
            )
                            
            process = await connection.fetchrow("""SELECT * FROM gradingprocess WHERE identifier = $1;""", str(process_id))

            if process is None:
                print(f"Process with ID {process_id} not found.")
                return
            
            send_mail(
                settings.EMAIL_HEADER,
                settings.MAIL_TEMPLATE_RENDERER(process['identifier']),
                settings.EMAIL_ADDRESS,
                [process['email']],
                html_message=settings.MAIL_TEMPLATE_RENDERER(process['identifier'])
                )
            print(f"Sent email to {process.email}")
        except Exception as e:
        # to error handling?
            print("Error while sending email:" + str(e))
        else:
            print(f"Notified {process['email']}\n") 
            await connection.execute("""UPDATE gradingprocess SET notified = true WHERE identifier = $1; """, process['identifier'])
        finally:
            await connection.close()
            print("Connection closed")

