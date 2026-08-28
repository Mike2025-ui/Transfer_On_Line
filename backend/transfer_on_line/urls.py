from django.contrib import admin
from django.urls import include, path
from rest_framework_simplejwt.views import TokenRefreshView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('apps.dashboard.urls')),
    path('dashboard/', include('apps.dashboard.urls')),
    path('api/', include("apps.devices.urls")),
    path('api/gateway/', include("apps.devices.urls")),
    path('api/payments/', include('apps.payments.urls')),
    path('api/health/', include('apps.core.urls')),
    path('api/auth/', include('apps.accounts.urls')),
    path('api/auth/token/refresh/', TokenRefreshView.as_view(), name='api_auth_token_refresh'),
]
