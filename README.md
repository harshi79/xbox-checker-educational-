# xbox-checker-educational-
# educational project only only tested with own accs and private only 
# Xbox Checker SaaS Platform

A production-ready FastAPI + Turso + Vercel platform for Xbox account checking with user accounts, rate limiting, admin panel, and response watermarking.

## 🚀 Quick Deploy

### 1. Set up Turso Database
```bash
# Install Turso CLI
curl -sSfL https://get.tur.so/install.sh | bash
turso auth login
turso db create xbox-checker
turso db tokens create xbox-checker
