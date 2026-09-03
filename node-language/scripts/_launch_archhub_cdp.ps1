$env:QTWEBENGINE_REMOTE_DEBUGGING = '9223'
Set-Location 'C:\Users\fargaly\00.ARCHUB\ArchHub'
Start-Process -FilePath pythonw `
              -ArgumentList 'app\main.py' `
              -WorkingDirectory 'C:\Users\fargaly\00.ARCHUB\ArchHub' `
              -PassThru
Write-Output 'launched'
