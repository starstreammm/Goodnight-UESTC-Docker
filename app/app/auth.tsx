import {
    createContext,
    useContext,
    useEffect,
    useState,
    type ReactNode,
} from "react";
import { api, ApiError } from "./api";

export type User = {
    id: number;
    username: string;
    display_name: string;
    role: "admin" | "user";
    builtin: number;
    must_change_password: number;
    account_count?: number;
};

export function userHomePath(user: User) {
    return user.role === "admin"
        ? "/admin"
        : `/user/${encodeURIComponent(user.username)}`;
}

type Auth = {
    user: User | null;
    loading: boolean;
    error: string;
    setUser: (user: User | null) => void;
    refresh: () => Promise<void>;
    logout: () => Promise<void>;
};
const AuthContext = createContext<Auth | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
    const [user, updateUser] = useState<User | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");
    function setUser(next: User | null) {
        setError("");
        updateUser(next);
    }
    async function refresh() {
        setError("");
        try {
            setUser(await (await api("/auth/me")).json());
        } catch (e) {
            if (e instanceof ApiError && e.status === 401) setUser(null);
            else
                setError(
                    e instanceof Error
                        ? e.message
                        : "Could not load your session",
                );
        } finally {
            setLoading(false);
        }
    }
    useEffect(() => {
        void refresh();
        const expired = () => setUser(null);
        window.addEventListener("session-expired", expired);
        return () => window.removeEventListener("session-expired", expired);
    }, []);
    async function logout() {
        await api("/auth/logout", "POST");
        setUser(null);
    }
    return (
        <AuthContext.Provider
            value={{ user, loading, error, setUser, refresh, logout }}
        >
            {children}
        </AuthContext.Provider>
    );
}

export function useAuth() {
    const value = useContext(AuthContext);
    if (!value) throw new Error("AuthProvider is required");
    return value;
}
