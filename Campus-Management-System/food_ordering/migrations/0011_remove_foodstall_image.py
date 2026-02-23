from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("food_ordering", "0010_seed_demo_stalls_and_menu"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="foodstall",
            name="image",
        ),
    ]
