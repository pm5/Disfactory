from django.http import HttpResponse, JsonResponse
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework.decorators import api_view
import datetime
import time
from django.db.models import Q

from ..models import Factory, Document, Image, ReportRecord
from ..models.document import DocumentDisplayStatusEnum
from ..utils import normalize_townname
from .zipcode import ZIP_CODE

def _generate_factories_query_set(townname, source, display_status):
    # display_status
    if display_status is not None:

        docs = Document.objects\
            .only("id", "factory_id")\
            .order_by("factory_id", "-created_at")\
            .distinct('factory_id')

        display_status_options = map((lambda item: item[1]),DocumentDisplayStatusEnum.CHOICES)
        if display_status == "處理中":
            display_status = [
                DocumentDisplayStatusEnum.INDICES["已排程稽查"],
                DocumentDisplayStatusEnum.INDICES["陳述意見期"],
                DocumentDisplayStatusEnum.INDICES["已勒令停工"],
                DocumentDisplayStatusEnum.INDICES["已排程拆除"],
            ]
            docs = docs.filter(display_status__in=display_status)
        else:
            if display_status not in display_status_options:
                display_status_choices = ",".join(display_status_options)
                return HttpResponse(
                    f"display_status: [{display_status_choices}]",
                    status=400
                )
            display_status = DocumentDisplayStatusEnum.INDICES[display_status]
            docs = docs.filter(display_status=display_status)

        factory_id_list = list(map(lambda item: item.factory_id, docs))
        queryset = Factory.objects.filter(id__in=factory_id_list)
    else:
        queryset = Factory.objects

    # townname
    if townname:
        queryset = queryset.filter(Q(townname__startswith=townname) | Q(townname__startswith=f"臺灣省{townname}"))

    # source
    if source is not None:
        queryset = queryset.filter(source=source)

    return queryset

@swagger_auto_schema(
    method="get",
    operation_summary="取得某個地區的工廠數量",
    responses={
        200: openapi.Response(
            "工廠, 公文與回報數量",
            openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "<縣市名稱>": openapi.Schema(
                        type=openapi.TYPE_OBJECT,
                        properties={
                            "factories": openapi.Schema(
                                type=openapi.TYPE_STRING,
                                description="工廠數量"
                            ),
                            "documents": openapi.Schema(
                                type=openapi.TYPE_STRING,
                                description="公文數量"
                            ),
                            "report_records": openapi.Schema(
                                type=openapi.TYPE_STRING,
                                description="總回報數量"
                            ),
                            "towns": openapi.Schema(
                                type=openapi.TYPE_OBJECT,
                                description="鄉鎮市的資料",
                                properties={
                                    "<鄉鎮市名>": openapi.Schema(
                                        type=openapi.TYPE_OBJECT,
                                        properties={
                                            "factories": openapi.Schema(
                                                type=openapi.TYPE_STRING,
                                                description="工廠數量"
                                            ),
                                            "documents": openapi.Schema(
                                                type=openapi.TYPE_STRING,
                                                description="公文數量"
                                            ),
                                            "report_records": openapi.Schema(
                                                type=openapi.TYPE_STRING,
                                                description="回報數量"
                                            ),
                                        }
                                    )
                                }
                            )
                        }
                    ),
                },
            ),
        ),
        400: "request failed"
    },
    manual_parameters=[
        openapi.Parameter(
            name="townname",
            in_=openapi.IN_QUERY,
            description=f"輸入縣市名稱，例如 (臺南市)，不輸入的話會回傳全台灣的統計",
            type=openapi.TYPE_STRING,
            required=False,
            example="臺南市",
        ),
        openapi.Parameter(
            name="source",
            in_=openapi.IN_QUERY,
            description=f"U or G",
            enum=["U", "G"],
            type=openapi.TYPE_STRING,
            required=False,
            example="u",
        ),
        openapi.Parameter(
            name="display_status",
            in_=openapi.IN_QUERY,
            description="""
            除了 document 預設的 display_status 之外，還有一個 "處理中" 的選項可以用，這個代表
            "已排程稽查", "陳述意見期", "已勒令停工", "已排程拆除" 這四種 display_status
            """,
            enum=[
                "已檢舉",
                "已排程稽查",
                "陳述意見期",
                "已勒令停工",
                "已發函斷電",
                "已排程拆除",
                "已拆除",
                "不再追蹤",
                "處理中",
            ],
            type=openapi.TYPE_STRING,
            required=False,
            example="u",
        ),
        openapi.Parameter(
            name="level",
            in_=openapi.IN_QUERY,
            description="選擇是否要顯示縣市與鄉鎮市區的資料, 如果要顯示縣市資料可使用 level=city 如果要顯示鄉鎮市區資料 level=town",
            type=openapi.TYPE_STRING,
            required=False,
            example="cities",
        ),
    ]
)
@api_view(["GET"])
def get_factories_count_by_townname(request):
    townname = request.GET.get("townname", None)
    if townname:
        townname = normalize_townname(townname)

    source = request.GET.get("source", None)
    if source and source not in ["G", "U"]:
        return HttpResponse(
            f"source: ['G' or 'U']",
            status=400
        )

    display_status = request.GET.get("display_status", None)
    level = request.GET.get("level", None)
    if level and (level != "city" and level != "town"):
        return HttpResponse(
            400,
            "level should be city or town"
        )

    if townname is None:
        cities = ZIP_CODE.keys()
        town = None
    else:
        city = townname[:3]
        town = townname[3:]

        if city and city not in ZIP_CODE:
            return HttpResponse(
                f"invalid townname {city}",
                status=400,
            )
        cities = [city]

        if not level:
            if city:
                level = "city"
            if town:
                level = "town"

    # all
    result = _get_factories_information(None, source, display_status)
    if level is None:
        return JsonResponse(result)

    # cities
    result["cities"] = {}
    for city in cities:
        result["cities"][city] = _get_factories_information(city, source, display_status)

    if level == "city":
        return JsonResponse(result)

    # towns
    for city in cities:
        if town:
            towns = [town]
        elif not town:
            towns = ZIP_CODE[city].keys()
        else:
            towns = []

        # towns
        result["cities"][city]["towns"] = {}
        for item in towns:
            full_town_name = f"{city}{item}"
            data = _get_factories_information(full_town_name, source, display_status)
            result["cities"][city]["towns"][item] = data

    return JsonResponse(result)


def _get_factories_information(townname, source, display_status):
    factories_queryset = _generate_factories_query_set(townname, source, display_status)
    n_factories = factories_queryset.count()

    id_list = factories_queryset.values_list('id', flat=True)
    report_records_queryset = ReportRecord.objects.prefetch_related('factory').filter(factory__in=id_list)
    if display_status:
        # Because the factories are filtered by document, so the number of factories should be equal to number of documents
        n_documents = n_factories
    else:
        documents_queryset = Document.objects.prefetch_related('factory').filter(factory__in=id_list)
        n_documents = documents_queryset.count()

    return {
        "factories": n_factories,
        "documents": n_documents,
        "report_records": report_records_queryset.count()
    }


@swagger_auto_schema(
    method="get",
    operation_summary="取得某個地區的照片的數量",
    responses={
        200: openapi.Response(
            "照片數量",
            openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "count": openapi.Schema(type=openapi.TYPE_STRING, description="統計數量"),
                },
            ),
        ),
        400: "request failed"
    },
    manual_parameters=[
        openapi.Parameter(
            name="townname",
            in_=openapi.IN_QUERY,
            description=f"可以只輸入縣市名稱，例如 (臺南市) 或者更詳細一點，例如 (臺南市善化區)，不輸入的話會回傳全台灣的統計",
            type=openapi.TYPE_STRING,
            required=False,
            example="臺南市",
        ),
        openapi.Parameter(
            name="source",
            in_=openapi.IN_QUERY,
            description=f"U or G",
            enum=["U", "G"],
            type=openapi.TYPE_STRING,
            required=False,
            example="u",
        ),
        openapi.Parameter(
            name="display_status",
            in_=openapi.IN_QUERY,
            description="""
            除了 document 預設的 display_status 之外，還有一個 "處理中" 的選項可以用，這個代表
            "已排程稽查", "陳述意見期", "已勒令停工" 這三種 display_status
            """,
            enum=[
                "已檢舉",
                "已排程稽查",
                "陳述意見期",
                "已勒令停工",
                "已發函斷電",
                "已排程拆除",
                "已拆除",
                "不再追蹤",
                "處理中",
            ],
            type=openapi.TYPE_STRING,
            required=False,
            example="u",
        ),
    ]
)
@api_view(["GET"])
def get_images_count_by_townname(request):
    townname = request.GET.get("townname", None)
    if townname:
        townname = normalize_townname(townname)
    source = request.GET.get("source", None)
    display_status = request.GET.get("display_status", None)

    factories_queryset = _generate_factories_query_set(townname, source, display_status)
    id_list = factories_queryset.values_list('id', flat=True)
    queryset = Image.objects.prefetch_related('factory').filter(factory__id__in=id_list)

    return JsonResponse({
        "count": queryset.count()
    })

@swagger_auto_schema(
    method="get",
    operation_summary="取得某個地區的回報紀錄數量",
    responses={
        200: openapi.Response(
            "回報紀錄數量",
            openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "count": openapi.Schema(type=openapi.TYPE_STRING, description="統計數量"),
                },
            ),
        ),
        400: "request failed"
    },
    manual_parameters=[
        openapi.Parameter(
            name="townname",
            in_=openapi.IN_QUERY,
            description=f"可以只輸入縣市名稱，例如 (臺南市) 或者更詳細一點，例如 (臺南市善化區)，不輸入的話會回傳全台灣的統計",
            type=openapi.TYPE_STRING,
            required=False,
            example="臺南市",
        ),
        openapi.Parameter(
            name="source",
            in_=openapi.IN_QUERY,
            description=f"U or G",
            enum=["U", "G"],
            type=openapi.TYPE_STRING,
            required=False,
            example="u",
        ),
        openapi.Parameter(
            name="display_status",
            in_=openapi.IN_QUERY,
            description="""
            除了 document 預設的 display_status 之外，還有一個 "處理中" 的選項可以用，這個代表
            "已排程稽查", "陳述意見期", "已勒令停工" 這三種 display_status
            """,
            enum=[
                "已檢舉",
                "已排程稽查",
                "陳述意見期",
                "已勒令停工",
                "已發函斷電",
                "已排程拆除",
                "已拆除",
                "不再追蹤",
                "處理中",
            ],
            type=openapi.TYPE_STRING,
            required=False,
            example="u",
        ),
    ]
)
@api_view(["GET"])
def get_report_records_count_by_townname(request):
    townname = request.GET.get("townname", None)
    if townname:
        townname = normalize_townname(townname)
    source = request.GET.get("source", None)
    display_status = request.GET.get("display_status", None)

    factories_queryset = _generate_factories_query_set(townname, source, display_status)
    id_list = factories_queryset.values_list('id', flat=True)
    queryset = ReportRecord.objects.prefetch_related('factory').filter(factory__in=id_list)

    return JsonResponse({
        "count": queryset.count()
    })


@swagger_auto_schema(
    method="get",
    operation_summary="統計全台灣各縣市的工廠情況, 處理進度與回報情況",
    responses={
        200: openapi.Response(
            "工廠, 公文與已回報的工廠數量",
            openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "<縣市名稱>": openapi.Schema(
                        type=openapi.TYPE_OBJECT,
                        properties={
                            "factories": openapi.Schema(
                                type=openapi.TYPE_INTEGER,
                                description="工廠數量"
                            ),
                            "documents": openapi.Schema(
                                type=openapi.TYPE_INTEGER,
                                description="公文數量"
                            ),
                            "report_records": openapi.Schema(
                                type=openapi.TYPE_INTEGER,
                                description="已經被回報的工廠的數量 (如果一個工廠有被回報多次，只會以一次計算)"
                            ),
                            "處理中": openapi.Schema(
                                type=openapi.TYPE_INTEGER,
                                description="""
                                    狀態為 "已排程稽查", "陳述意見期", "已勒令停工", "已排程拆除" 的工廠數量
                                """
                            ),
                            "未處理": openapi.Schema(
                                type=openapi.TYPE_INTEGER,
                                description="""
                                    狀態為 "未處理" 的工廠數量
                                """
                            ),
                            "已斷電": openapi.Schema(
                                type=openapi.TYPE_INTEGER,
                                description="""
                                    狀態為 "已斷電" 的工廠數量
                                """
                            ),
                            "已拆除": openapi.Schema(
                                type=openapi.TYPE_INTEGER,
                                description="""
                                    狀態為 "已拆除" 的工廠數量
                                """
                            ),
                        }
                    ),
                },
            ),
        ),
        400: "request failed"
    },
)
@api_view(["GET"])
def get_statistics_total(request):
    result = {}
    cities = ZIP_CODE.keys()
    for city in cities:
        city = city.replace("台", "臺")
        result[city] = {}

        # factories
        factories = Factory.objects.filter(Q(townname__startswith=city) | Q(townname__startswith=f"臺灣省{city}"))
        result[city]["factories"] = factories.count()

        # report records
        factory_id_list = factories.values_list('id', flat=True)
        report_records = ReportRecord.objects.prefetch_related('factory').filter(factory__id__in=factory_id_list).distinct("factory_id")
        result[city]["report_records"] = report_records.count()

        # display_status
        docs = Document.objects.prefetch_related("factory")\
                               .order_by("factory__id", "-created_at")\
                               .distinct('factory__id')\
                               .filter(factory__id__in=factory_id_list)

        result[city]["documents"] = docs.count()

        ## 處理中
        result[city]["未處理"] = 0
        result[city]["處理中"] = 0
        result[city]["已斷電"] = 0
        result[city]["已拆除"] = 0

        for doc in docs:
            if doc.display_status == DocumentDisplayStatusEnum.INDICES["已檢舉"]:
                result[city]["未處理"] += 1
            elif doc.display_status == DocumentDisplayStatusEnum.INDICES["已排程稽查"] or \
                 doc.display_status == DocumentDisplayStatusEnum.INDICES["陳述意見期"] or \
                 doc.display_status == DocumentDisplayStatusEnum.INDICES["已勒令停工"] or \
                 doc.display_status == DocumentDisplayStatusEnum.INDICES["已排程拆除"]:
                result[city]["處理中"] += 1
            elif doc.display_status == DocumentDisplayStatusEnum.INDICES["已發函斷電"]:
                result[city]["已斷電"] += 1
            elif doc.display_status == DocumentDisplayStatusEnum.INDICES["已拆除"]:
                result[city]["已拆除"] += 1

    return JsonResponse(result)
