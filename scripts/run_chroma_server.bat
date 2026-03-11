@echo off
echo ===================================================
echo   AURA-FLASH: CHROMA DB REST SERVER (PHASE 4.1)
echo ===================================================
echo WARNING: Xin hay chac chan ban dang chay terminal nay
echo bang moi truong Python 3.12 (hoac thap hon), KHONG 
echo phai Python 3.14!
echo.
echo Khoi tao Chroma DB tai: ../outputs/chroma_db
chroma run --path ../outputs/chroma_db --port 8000
pause
