from django.urls import path

from . import views

urlpatterns = [
    path('gateways/', views.GatewayListView.as_view(), name='api_gateways'),
    path('gateways/heartbeat/', views.GatewayHeartbeatView.as_view(), name='api_gateway_heartbeat_create'),
    path('gateways/<int:gateway_id>/heartbeat/', views.GatewayHeartbeatView.as_view(), name='api_gateway_heartbeat'),
    path('transactions/execute/', views.ExecuteTransactionView.as_view(), name='api_transaction_execute'),
    path('transactions/pending/', views.PendingTransactionsView.as_view(), name='api_transaction_pending'),
    path('transactions/result/', views.TransactionResultView.as_view(), name='api_transaction_result'),
]
