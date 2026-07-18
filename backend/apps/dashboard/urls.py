from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard_index, name='dashboard'),
    path('transactions/', views.transactions_list, name='transactions'),
    path('remboursements/', views.refunds_list, name='refunds'),
    path('gateways/', views.gateways_list, name='gateways'),
    path('clients/', views.clients_list, name='clients'),
    path('rapports/', views.reports_list, name='reports'),
    path('notifications/', views.notifications_list, name='notifications'),
    path('parametres/', views.settings_view, name='settings'),
    path('audit/', views.audit_logs, name='audit'),
]