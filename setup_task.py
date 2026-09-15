"""创建带唤醒功能的定时任务（需管理员权限运行）"""
import subprocess
import sys

task_name = "AI_Paper_Downloader"
script_path = r"C:\Users\50464\Desktop\论文\_scripts\main.py"

# 删除旧任务
subprocess.run(["schtasks", "/delete", "/tn", task_name, "/f"], capture_output=True)

# 创建新任务
result = subprocess.run([
    "schtasks", "/create", "/tn", task_name,
    "/tr", f"python {script_path}",
    "/sc", "daily", "/st", "09:00",
    "/ru", "SYSTEM", "/rl", "HIGHEST", "/it"
], capture_output=True, text=True)

print(result.stdout, result.stderr)

# 设置唤醒功能
script = f"""
$task = Get-ScheduledTask -TaskName '{task_name}'
$settings = $task.Settings
$settings.WakeToRun = $true
$settings.StartWhenAvailable = $true
Set-ScheduledTask -TaskName '{task_name}' -Settings $settings
"""
result2 = subprocess.run(["powershell", "-Command", script], capture_output=True, text=True)
print(result2.stdout, result2.stderr)

print("完成！请在任务计划程序中确认设置。")
