"# TakeOff.ai Test Credentials

## Test Users

### User 1: Alex Rivera (ACME Construction)
- **Email:** alex@acme.com
- **Password:** password123
- **Organization:** ACME Construction
- **Role:** Project Owner

### User 2: Priya Patel (BuildRight LLC)
- **Email:** priya@buildr.com  
- **Password:** password123
- **Organization:** BuildRight LLC
- **Role:** Project Owner

### User 3: Demo User (ACME Construction)
- **Email:** demo@takeoff.ai
- **Password:** demo2025
- **Organization:** ACME Construction
- **Role:** Demo Account

## Sample Projects (for alex@acme.com)

1. **Waterford Tower — Level 12**
   - Type: High-rise residential
   - Status: Active

2. **Meridian Medical Campus**
   - Type: Healthcare
   - Status: Active

3. **Oak Grove Elementary Renovation**
   - Type: Education
   - Status: Review

## API Endpoints

### Base URL
- Development: `http://localhost:8001/api`

### Authentication
- Login: `POST /api/auth/login`
- Signup: `POST /api/auth/signup`
- Get Current User: `GET /api/auth/me` (requires Bearer token)

### Projects
- List Projects: `GET /api/projects` (requires auth)
- Create Project: `POST /api/projects` (requires auth)
- Get Project: `GET /api/projects/{id}` (requires auth)
- Update Project: `PUT /api/projects/{id}` (requires auth)
- Delete Project: `DELETE /api/projects/{id}` (requires auth)

### Uploads
- Upload Drawing: `POST /api/uploads/project/{project_id}/drawings` (requires auth)
- List Drawings: `GET /api/uploads/project/{project_id}/drawings` (requires auth)
- Get Drawing: `GET /api/uploads/drawings/{drawing_id}` (requires auth)

## Example API Usage

### Login
```bash
curl -X POST http://localhost:8001/api/auth/login \
  -H \"Content-Type: application/json\" \
  -d '{\"email\":\"alex@acme.com\",\"password\":\"password123\"}'
```

### Get Projects (with token)
```bash
TOKEN=\"your_token_here\"
curl -X GET http://localhost:8001/api/projects \
  -H \"Authorization: Bearer $TOKEN\"
```
"