from django.contrib import admin, messages

from .models import *


class ProcessedFilter(admin.SimpleListFilter):
    title = "processed status"
    parameter_name = "processed"

    def lookups(self, request, model_admin):
        return [
            ("yes", "Processed"),
            ("no", "Unprocessed (stuck)"),
        ]

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(
                models.Q(grading__isnull=False) | models.Q(errorlog__isnull=False)
            ).distinct()
        if self.value() == "no":
            return queryset.filter(grading__isnull=True, errorlog__isnull=True)


@admin.action(description="Delete unprocessed grading processes")
def delete_unprocessed_action(modeladmin, request, queryset):
    to_delete = queryset.filter(grading__isnull=True, errorlog__isnull=True)
    count, _ = to_delete.delete()
    modeladmin.message_user(request, f"{count} unprocessed grading process(es) deleted.", messages.SUCCESS)

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
    list_filter = [ProcessedFilter, "for_exercise"]
    ordering = ["-requested_at"]
    actions = [delete_unprocessed_action]

class DailyLimitAdmin(admin.ModelAdmin):
    model = DailyLimit
    list_display = ["user_id", "limit"]
    readonly_fields = ["user_id"]

admin.site.register(Exercise, ExerciseAdmin)

admin.site.register(SubExercise, SubExercisesAdmin)

admin.site.register(GradingProcess, ProcessAdmin)

admin.site.register(DailyLimit, DailyLimitAdmin)

admin.site.register(StudentNotebook)

admin.site.register(WorkerAssignment)

admin.site.register(Grading)

admin.site.register(ErrorLog)