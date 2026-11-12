// Which business is open on screen right now (a business screen, or a person's record in it).
// Typed and spoken entries use it when the sentence doesn't name a business.
let current = null;
export const setOpenBusiness = (id) => { current = id ? Number(id) : null; };
export const getOpenBusiness = () => current;
