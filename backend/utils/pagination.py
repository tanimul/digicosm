"""
Shared pagination classes for the DCE platform.
"""

from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class StandardPagination(PageNumberPagination):
    """Default pagination: 20 items/page, max 100."""

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100

    def get_paginated_response(self, data):
        return Response({
            "success": True,
            "count": self.page.paginator.count,
            "next": self.get_next_link(),
            "previous": self.get_previous_link(),
            "results": data,
        })

    def get_paginated_response_schema(self, schema):
        return {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "count": {"type": "integer"},
                "next": {"type": "string", "nullable": True},
                "previous": {"type": "string", "nullable": True},
                "results": schema,
            },
        }


class LargePagination(PageNumberPagination):
    """For admin list views: 50 items/page, max 200."""

    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200

    def get_paginated_response(self, data):
        return Response({
            "success": True,
            "count": self.page.paginator.count,
            "next": self.get_next_link(),
            "previous": self.get_previous_link(),
            "results": data,
        })


class SmallPagination(PageNumberPagination):
    """For mobile / widget views: 10 items/page, max 50."""

    page_size = 10
    page_size_query_param = "page_size"
    max_page_size = 50

    def get_paginated_response(self, data):
        return Response({
            "success": True,
            "count": self.page.paginator.count,
            "next": self.get_next_link(),
            "previous": self.get_previous_link(),
            "results": data,
        })
