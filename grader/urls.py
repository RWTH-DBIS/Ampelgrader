from django.urls import path

from . import views

urlpatterns = [
    path("ping", views.ping, name="ping"),
    path("login", views.login, name="login"),
    path("request/<str:for_exercise>", views.request_grading, name="request"),
    path("successful_request", views.successful_request, name="successful_request"),
    path("autocreation", views.autoprocess_notebook, name="autocreate"),
]
