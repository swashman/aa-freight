"""Routes for Freight."""

from django.urls import path

from . import views

app_name = "freight"

urlpatterns = [
    path("", views.index, name="index"),
    path(
        "setup_contract_handler",
        views.setup_contract_handler,
        name="setup_contract_handler",
    ),
    path("add_location", views.add_location, name="add_location"),
    path("add_location_2", views.add_location_2, name="add_location_2"),
    path("calculator", views.calculator, name="calculator"),
    path("calculator/<int:pricing_pk>", views.calculator, name="calculator"),
    path("contract_list_all", views.contract_list_all, name="contract_list_all"),
    path("contract_list_user", views.contract_list_user, name="contract_list_user"),
    path(
        "contract_list_data/<str:category>",
        views.contract_list_data,
        name="contract_list_data",
    ),
    path("statistics", views.statistics, name="statistics"),
    path(
        "statistics_routes_data",
        views.statistics_routes_data,
        name="statistics_routes_data",
    ),
    path(
        "statistics_pilots_data",
        views.statistics_pilots_data,
        name="statistics_pilots_data",
    ),
    path(
        "statistics_pilot_corporations_data",
        views.statistics_pilot_corporations_data,
        name="statistics_pilot_corporations_data",
    ),
    path(
        "statistics_customer_data",
        views.statistics_customer_data,
        name="statistics_customer_data",
    ),
]
