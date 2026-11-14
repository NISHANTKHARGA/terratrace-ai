# TerraTrace AI — Deployment Guide (Vercel + Supabase + Render)

## Architecture
- **Frontend**: Vercel (React + Vite)
- **Backend**: Render (Python/FastAPI/Docker)
- **Database**: Supabase (PostgreSQL)
- **Storage**: Supabase Storage (artifacts)

---

## Step 1: Create Supabase Project

1. Go to https://supabase.com → **New Project**
2. Name: `terratrace-ai`
3. Set a strong database password
4. Region: choose closest to your users
5. Wait for project to be ready

### Get your credentials
- **Project URL**: Settings → API → Project URL
- **Anon Key**: Settings → API → anon/public key
- **Service Role Key**: Settings → API → service_role key (for backend)
- **Database URL**: Settings → Database → Connection string → URI mode
  - Format: `postgresql://postgres:YOUR-PASSWORD@db.YOUR-PROJECT.supabase.co:5432/postgres`

### Create Storage Bucket
1. Go to **Storage** → **New Bucket**
2. Name: `terratrace-artifacts`
3. Make it **Public** (so artifact URLs work)
4. Set file size limit: 50 MB

---

## Step 2: Deploy Backend to Render

1. Go to https://render.com → **New** → **Web Service**
2. Connect your GitHub repo
3. Settings:
   - **Name**: `terratrace-ai-backend`
   - **Runtime**: Docker
   - **Dockerfile Path**: `backend/Dockerfile`
   - **Docker Context**: `backend`
   - **Plan**: Free (or Starter for better performance)
4. Environment Variables:
   ```
   DATABASE_URL=postgresql://postgres:YOUR-PASSWORD@db.YOUR-PROJECT.supabase.co:5432/postgres
   DATA_DIR=/app/data
   ARTIFACTS_DIR=/app/data/artifacts
   SUPABASE_URL=https://YOUR-PROJECT.supabase.co
   SUPABASE_KEY=your-service-role-key
   SUPABASE_STORAGE_BUCKET=terratrace-artifacts
   USE_SUPABASE_STORAGE=true
   ALLOWED_ORIGINS=["https://terratrace-ai.vercel.app","http://localhost:5173"]
   EARTHDATA_USERNAME=your-username
   EARTHDATA_PASSWORD=your-password
   EARTHDATA_TOKEN=your-token
   ```
5. Add a **Disk**:
   - Name: `terratrace-data`
   - Mount Path: `/app/data`
   - Size: 1 GB
6. Click **Create Web Service**
7. Wait for build to complete
8. Note your backend URL: `https://terratrace-ai-backend.onrender.com`

---

## Step 3: Deploy Frontend to Vercel

1. Go to https://vercel.com → **Add New** → **Project**
2. Import your GitHub repo
3. Settings:
   - **Framework Preset**: Vite
   - **Root Directory**: `frontend`
   - **Build Command**: `npm run build`
   - **Output Directory**: `dist`
4. Environment Variables:
   ```
   VITE_API_BASE=https://terratrace-ai-backend.onrender.com
   ```
5. Click **Deploy**
6. Note your frontend URL: `https://terratrace-ai.vercel.app`

---

## Step 4: Update CORS

After deploying, update the backend's `ALLOWED_ORIGINS` env var on Render to include your actual Vercel URL:
```
ALLOWED_ORIGINS=["https://terratrace-ai.vercel.app","http://localhost:5173"]
```

---

## Step 5: Verify

1. Open your Vercel URL
2. Check the status dot (should show "ready" or "partial")
3. Select an area → Analyze → watch the 12 agents → view the report
4. Check `/map` for the NASA satellite basemap
5. Check `/reports` for saved analyses

---

## Supabase Database Setup

The backend automatically creates tables on startup. No manual migration needed.

If you want to use Supabase's connection pooler (recommended for serverless):
- Use the **Transaction** pooler URL (port 6543)
- Format: `postgresql://postgres:PASSWORD@aws-0-REGION.pooler.supabase.com:6543/postgres`

---

## Troubleshooting

### Backend won't start
- Check Render logs for Python errors
- Ensure all env vars are set
- Verify DATABASE_URL is correct

### Frontend can't reach backend
- Check VITE_API_BASE is set correctly
- Check ALLOWED_ORIGINS includes your Vercel URL
- Check Render service is running (free tier sleeps after 15 min inactivity)

### Analysis jobs timeout
- Render free tier has 15 min timeout
- Consider upgrading to Starter plan for longer timeouts
- Or reduce RASTER_SIZE and MAX_OBSERVATIONS

### Artifacts not loading
- Verify Supabase Storage bucket is public
- Check SUPABASE_KEY has storage permissions
- Check USE_SUPABASE_STORAGE=true
