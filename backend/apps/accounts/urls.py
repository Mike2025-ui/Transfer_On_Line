from django.urls import path

from . import views

urlpatterns = [
    path('otp/request/', views.RequestOtpView.as_view(), name='api_auth_otp_request'),
    path('otp/verify/', views.VerifyOtpView.as_view(), name='api_auth_otp_verify'),
]
