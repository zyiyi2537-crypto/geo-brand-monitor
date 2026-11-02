import { createContext, useContext, useState, useCallback, type ReactNode } from 'react';

interface TierModalContextValue {
  isOpen: boolean;
  openTierModal: () => void;
  closeTierModal: () => void;
}

const TierModalContext = createContext<TierModalContextValue>({
  isOpen: false,
  openTierModal: () => {},
  closeTierModal: () => {},
});

export function TierModalProvider({ children }: { children: ReactNode }) {
  const [isOpen, setIsOpen] = useState(false);
  const openTierModal = useCallback(() => setIsOpen(true), []);
  const closeTierModal = useCallback(() => setIsOpen(false), []);

  return (
    <TierModalContext.Provider value={{ isOpen, openTierModal, closeTierModal }}>
      {children}
    </TierModalContext.Provider>
  );
}

export function useTierModal() {
  return useContext(TierModalContext);
}
