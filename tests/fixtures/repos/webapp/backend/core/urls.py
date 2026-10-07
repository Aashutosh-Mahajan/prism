from django.urls import path

from . import views

urlpatterns = [
    path("auth/login/", views.LoginView.as_view()),
    path("auth/verify-email/", views.VerifyEmailView.as_view()),
]
