from django import forms


class NoteBookForm(forms.Form):
    notebook = forms.FileField()


class DateInput(forms.DateTimeInput):
    input_type = "datetime-local"


class AutoCreationForm(forms.Form):
    notebook = forms.FileField(label="Notebook file")
    start_date = forms.DateTimeField(
        label="Start date of autograde period", widget=DateInput
    )
    stop_date = forms.DateTimeField(
        label="Stop date of autograde period", widget=DateInput
    )
    exercise_identifier = forms.CharField(
        label="Identifier for the Exercise", max_length=255
    )
