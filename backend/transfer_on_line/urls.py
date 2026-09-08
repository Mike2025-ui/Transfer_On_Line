from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('apps.dashboard.urls')),
    path('dashboard/', include('apps.dashboard.urls')),
    path('api/', include("apps.devices.urls")),
    path('api/gateway/', include("apps.devices.urls")),
    path('api/payments/', include('apps.payments.urls')),
    path('api/health/', include('apps.core.urls')),
]
