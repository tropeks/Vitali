from rest_framework.pagination import PageNumberPagination


class StandardResultsSetPagination(PageNumberPagination):
    """Global bounded pagination with an explicit client page-size contract."""

    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200
