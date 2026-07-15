@echo off
cd /d "%~dp0"
python scripts\update_wordpress_posts.py %*
