import {
    createContext,
    useContext,
    useEffect,
    useState,
    type ReactNode,
} from "react";
import { api, ApiError } from "./api";

export const LAST_USERNAME_STORAGE_KEY = "goodnight-last-username:v1";

export type User = {
    id: number;
    username: string;
    display_name: string;
    role: "admin" | "user";
    builtin: number;
    must_change_password: number;
    account_count?: number;
    language?: "en" | "zh";
    bark_enabled?: number;
    bark_configured?: number;
    bark_prompt_dismissed?: number;
};

export type Preferences = {
    language?: "en" | "zh";
    bark_enabled?: boolean;
    bark_key?: string;
    bark_prompt_dismissed?: true;
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
    updatePreferences: (preferences: Preferences) => Promise<void>;
};
const AuthContext = createContext<Auth | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
    const [user, updateUser] = useState<User | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");
    function setUser(next: User | null) {
        setError("");
        updateUser((previous) => {
            // Dismissal is permanent; an older polling response cannot undo it.
            if (
                next && previous?.id === next.id && previous.bark_prompt_dismissed
            ) {
                return { ...next, bark_prompt_dismissed: 1 };
            }
            return next;
        });
        if (next) {
            try {
                localStorage.setItem(LAST_USERNAME_STORAGE_KEY, next.username);
            } catch (error) {
                // Remembering the username is optional when storage is blocked.
                console.warn("Could not remember the last username", error);
            }
        }
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
    async function updatePreferences(preferences: Preferences) {
        const response = await api("/auth/preferences", "PATCH", preferences);
        setUser(await response.json());
    }
    return (
        <AuthContext.Provider
            value={{
                user,
                loading,
                error,
                setUser,
                refresh,
                logout,
                updatePreferences,
            }}
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
