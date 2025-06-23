from django.contrib import admin

from .models import *

admin.site.site_header = "Nbgrader Admin Panel"
admin.site.index_title = "Nbgrader Verwaltung"

# Register your models here.

class CellInline(admin.TabularInline):
    model = Cell
    extra = 3


class GradingInline(admin.TabularInline):
    model = Grading


class ErrorLogInline(admin.StackedInline):
    model = ErrorLog


class StudentNotebookInline(admin.TabularInline):
    model = StudentNotebook

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.only("process", "notebook")

class SubExercisesAdmin(admin.ModelAdmin):
    model = SubExercise
    extra = 1
    inlines = [CellInline]
    list_filter = ["in_notebook"]
    list_display = ["in_notebook", "label"]


class NotebookAdmin(admin.StackedInline):
    model = Notebook

class ExerciseAdmin(admin.ModelAdmin):
    model = Exercise
    inlines = [NotebookAdmin]
    list_display = ["identifier", "start_date", "stop_date", "running", "last_updated"]
    readonly_fields = ["identifier"]
    ordering = ["-start_date", "-last_updated"]

    def has_delete_permission(self, request, obj = None):
        return False

class ProcessAdmin(admin.ModelAdmin):
    model = GradingProcess
    inlines = [GradingInline, StudentNotebookInline, ErrorLogInline]
    list_display = ["identifier", "email", "requested_at", "for_exercise", "processed"]
    ordering = ["-requested_at"]

class DailyContingentAdmin(admin.ModelAdmin):
    model = DailyContingent
    list_display = ["user_email", "date", "count"]
    readonly_fields = ["user_email", "date"]

admin.site.register(Exercise, ExerciseAdmin)

admin.site.register(SubExercise, SubExercisesAdmin)

admin.site.register(GradingProcess, ProcessAdmin)

admin.site.register(DailyContingent, DailyContingentAdmin)

admin.site.register(StudentNotebook)

admin.site.register(WorkerAssignment)

admin.site.register(Grading)

admin.site.register(ErrorLog)