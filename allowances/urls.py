from django.urls import path

from . import views

app_name = "allowances"

urlpatterns = [
    path("", views.record_list, name="list"),
    path("new/", views.record_create, name="create"),
    path("lookup/", views.record_lookup, name="lookup"),
    path("<int:pk>/", views.record_detail, name="detail"),
    path("<int:pk>/edit/", views.record_update, name="update"),
    path("<int:pk>/delete/", views.record_delete, name="delete"),
]
