# Firestore Emulator with Java 21
FROM google/cloud-sdk:latest

# Install Java 21 JRE from Adoptium (required for Firestore emulator)
RUN apt-get update && \
    apt-get install -y wget apt-transport-https gnupg curl && \
    wget -qO - https://packages.adoptium.net/artifactory/api/gpg/key/public | gpg --dearmor -o /usr/share/keyrings/adoptium-archive-keyring.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/adoptium-archive-keyring.gpg] https://packages.adoptium.net/artifactory/deb bookworm main" | tee /etc/apt/sources.list.d/adoptium.list && \
    apt-get update && \
    apt-get install -y temurin-21-jre && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Verify Java installation
RUN java -version

# Expose Firestore emulator port
EXPOSE 8080

# Start Firestore emulator
CMD ["gcloud", "beta", "emulators", "firestore", "start", "--host-port=0.0.0.0:8080"]
