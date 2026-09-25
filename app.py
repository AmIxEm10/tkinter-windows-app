import tkinter as tk

def fermer_application():
    fenetre.destroy()

fenetre = tk.Tk()
fenetre.title("Application Tkinter")
fenetre.geometry("300x120")
fenetre.resizable(False, False)

bouton_fermer = tk.Button(fenetre, text="Fermer l'application", command=fermer_application, width=20, height=2)
bouton_fermer.pack(expand=True)

fenetre.mainloop()
