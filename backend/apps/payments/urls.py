from django.urls import path

from . import webhooks

urlpatterns = [
    path('cinetpay/notify/', webhooks.CinetPayNotifyView.as_view(), name='api_cinetpay_notify'),
    path('geniuspay/webhook/', webhooks.GeniusPayWebhookView.as_view(), name='api_geniuspay_webhook'),
    path('jeko/webhook/', webhooks.JekoWebhookView.as_view(), name='api_jeko_webhook'),
]
