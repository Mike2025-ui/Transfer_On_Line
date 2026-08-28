from django.urls import path

from . import views

urlpatterns = [
    path('gateways/', views.GatewayListView.as_view(), name='api_gateways'),
    path('gateways/heartbeat/', views.GatewayHeartbeatView.as_view(), name='api_gateway_heartbeat_create'),
    path('gateways/<int:gateway_id>/heartbeat/', views.GatewayHeartbeatView.as_view(), name='api_gateway_heartbeat'),
    path('transactions/execute/', views.ExecuteTransactionView.as_view(), name='api_transaction_execute'),
    path('transactions/<str:reference>/status/', views.TransactionStatusView.as_view(), name='api_transaction_status'),
    path('operators/', views.OperatorListView.as_view(), name='api_operators'),
    path('services/', views.ServiceListView.as_view(), name='api_services'),
    path(
        'operators/<int:operator_id>/services/<int:service_id>/amounts/',
        views.AmountListView.as_view(), name='api_amounts',
    ),
    path('transactions/pending/', views.PendingTransactionsView.as_view(), name='api_transaction_pending'),
    path('transactions/result/', views.TransactionResultView.as_view(), name='api_transaction_result'),
    path('transactions/step/', views.TransactionStepView.as_view(), name='api_transaction_step'),
    path('sms/pending/', views.SmsPendingView.as_view(), name='api_sms_pending'),
    path('sms/result/', views.SmsResultView.as_view(), name='api_sms_result'),
]
