"""Set daily limit for users command."""
from django.core.management.base import BaseCommand
from django.conf import settings
from django.contrib.auth.models import User
from grader.models import DailyLimit

class Command(BaseCommand):
    help = 'Set daily limit for all users without a specific limit to the default value from environment variable'

    def handle(self, *args, **kwargs):
        default_limit = settings.DAILY_LIMIT
        for user in User.objects.all():
            DailyLimit.objects.get_or_create(
                user_id=user, 
                defaults={'limit': default_limit}
            )
        self.stdout.write(self.style.SUCCESS('Successfully set daily limits for all users'))