from django.urls import path

from .views import (
    AIUsageView,
    GlosaPredictBatchView,
    GlosaPredictView,
    TUSSSuggestFeedbackView,
    TUSSSuggestView,
)

urlpatterns = [
    path("ai/tuss-suggest/", TUSSSuggestView.as_view(), name="ai-tuss-suggest"),
    path(
        "ai/tuss-suggest/feedback/",
        TUSSSuggestFeedbackView.as_view(),
        name="ai-tuss-suggest-feedback",
    ),
    path("ai/glosa-predict/", GlosaPredictView.as_view(), name="ai-glosa-predict"),
    path(
        "ai/glosa-predict-batch/",
        GlosaPredictBatchView.as_view(),
        name="ai-glosa-predict-batch",
    ),
    path("ai/usage/", AIUsageView.as_view(), name="ai-usage"),
]
