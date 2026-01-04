import { initializeApp } from "https://www.gstatic.com/firebasejs/10.9.0/firebase-app.js";
import { getAuth, 
         GoogleAuthProvider } from "https://www.gstatic.com/firebasejs/10.9.0/firebase-auth.js";
import { getFirestore } from "https://www.gstatic.com/firebasejs/10.9.0/firebase-firestore.js";

// Your web app's Firebase configuration
const firebaseConfig = {
  apiKey: "AIzaSyAr-NFvIz8McWg9hpeJHNc-dmT0w1z6t1E",
  authDomain: "stemsplit-c1d29.firebaseapp.com",
  projectId: "stemsplit-c1d29",
  storageBucket: "stemsplit-c1d29.firebasestorage.app",
  messagingSenderId: "952424381420",
  appId: "1:952424381420:web:e71c3cfba4d0b8a44c1ec9",
  measurementId: "G-5C38PN3PJ4"
};

  // Initialize Firebase
const app = initializeApp(firebaseConfig);
const auth = getAuth(app);
const provider = new GoogleAuthProvider();

const db = getFirestore(app);

export { auth, provider, db };