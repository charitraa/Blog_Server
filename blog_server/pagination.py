"""Pagination classes shared by every list endpoint."""

from rest_framework.pagination import PageNumberPagination


class StandardPagination(PageNumberPagination):
    """
    Keeps the DRF response envelope the frontend already expects:

        {"count": 120, "next": "...", "previous": null, "results": [...]}

    Clients may request a different page size with `?page_size=`, capped so a
    single request can never ask the database for an unbounded result set.
    """

    page_size_query_param = 'page_size'
    max_page_size = 50


class LargePagination(StandardPagination):
    """For collections that are cheap to serialize, such as comments."""

    page_size = 20
    max_page_size = 100
