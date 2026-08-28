from django.urls import path

from . import views

urlpatterns = [
    path('', views.HealthCheckView.as_view(), name='api_health'),
    path('live/', views.LivenessView.as_view(), name='api_health_live'),
    path('ready/', views.ReadinessView.as_view(), name='api_health_ready'),
]
