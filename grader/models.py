import uuid

from django.db import models


class Exercise(models.Model):
    identifier = models.CharField(max_length=255, primary_key=True)
    startDate = models.DateField()
    stopDate = models.DateField()

    def __str__(self):
        return f"ID: {self.identifier} Correction from {self.startDate} to {self.stopDate}."

class GradingProcess(models.Model):
    identifier = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField()
    requestedAt = models.DateTimeField(auto_now_add=True)
    forExercise = models.ForeignKey(Exercise, on_delete=models.CASCADE)

    def __str__(self):
        return f"ID: {self.identifier} for email: {self.email}. Request at: {self.requestedAt.__str__()}"


class Notebook(models.Model):
    filename = models.CharField(max_length=255, primary_key=True)
    inExercise = models.ForeignKey(Exercise, on_delete=models.CASCADE)
    cells = models.JSONField(verbose_name="Cells definitions")

class Grading(models.Model):
    processId = models.OneToOneField(GradingProcess, on_delete=models.CASCADE)
    points = models.IntegerField()