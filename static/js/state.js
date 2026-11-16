// Sirf yaad-dasht mein (browser storage mein nahi): kaun login hai.
export const state = { user: null, timer: null, next: null, notice: null };
export const isStaff = () => !!state.user && ["coordinator", "admin"].includes(state.user.role);
