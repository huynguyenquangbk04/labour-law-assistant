FROM postgres:16

# Install dependencies for building Apache AGE and pgvector
RUN apt-get update && apt-get install -y \
  build-essential \
  git \
  postgresql-server-dev-16 \
  postgresql-16-pgvector \
  libcap-dev \
  bison \
  flex \
  && rm -rf /var/lib/apt/lists/*

# Build and Install Apache AGE (PostgreSQL 16 compatible)
RUN git clone --branch PG16 --depth 1 https://github.com/apache/age.git /tmp/age && \
  cd /tmp/age && \
  make install && \
  rm -rf /tmp/age

# Ensure standard extensions are available (pgvector is already in apt for pg16, but we'll ensure it's registered)
RUN echo "shared_preload_libraries = 'age'" >> /usr/share/postgresql/postgresql.conf.sample

# Copy initialization script
COPY init-db.sh /docker-entrypoint-initdb.d/
RUN chmod +x /docker-entrypoint-initdb.d/init-db.sh