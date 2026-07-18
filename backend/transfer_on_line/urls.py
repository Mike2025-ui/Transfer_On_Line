from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('apps.dashboard.urls')),
    path('dashboard/', include('apps.dashboard.urls')),
    path('api/', include('apps.gateway.urls')),
    path('api/gateway/', include('apps.gateway.urls')),
]
