from django.urls import path, re_path

from . import views

urlpatterns = [
    path("ping", views.ping, name="ping"),
    path("login", views.login, name="login"),
    path("request/", views.show_exercises, name="show_exercises"),
    path("request/<str:for_exercise>", views.request_grading, name="request"),
    path("results/<str:for_process>", views.show_results, name="grading_results"),
    path("successful_request", views.successful_request, name="successful_request"),
    path("autocreation", views.autoprocess_notebook, name="autocreate"),
]
