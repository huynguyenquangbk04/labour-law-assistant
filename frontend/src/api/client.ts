import axios from 'axios'

const client = axios.create({
    baseURL: (import.meta as any).env.VITE_API_BASE_URL || 'http://localhost:8000/api', 
    headers: {
        'Content-Type': 'application/json'
    }
})

export default client