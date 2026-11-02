import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useContactModal } from '../components/ContactModalContext';

export function Contact() {
  const navigate = useNavigate();
  const { openContact } = useContactModal();

  useEffect(() => {
    openContact();
    navigate('/', { replace: true });
  }, [openContact, navigate]);

  return null;
}
