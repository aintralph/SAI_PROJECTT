from django.contrib import admin

from .models import Department, UserProfile

# dirii para maka add/edit departments and profiles sa /admin/


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "created_at")
    search_fields = ("code", "name")


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "department", "employee_id", "created_at")
    list_filter = ("department",)
    search_fields = ("user__username", "employee_id")
