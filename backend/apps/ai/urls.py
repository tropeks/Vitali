from django.urls import path
from .views import TUSSSuggestView, TUSSSuggestFeedbackView, AIUsageView

urlpatterns = [
    path('ai/tuss-suggest/', TUSSSuggestView.as_view(), name='ai-tuss-suggest'),
    path('ai/tuss-suggest/feedback/', TUSSSuggestFeedbackView.as_view(), name='ai-tuss-suggest-feedback'),
    path('ai/usage/', AIUsageView.as_view(), name='ai-usage'),
]
