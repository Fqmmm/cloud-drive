FROM maven:3.9.9-eclipse-temurin-17 AS build
WORKDIR /build
ARG MAVEN_MIRROR_URL=
COPY docker/maven-build.sh /usr/local/bin/course-maven-build
COPY file-service/pom.xml pom.xml
COPY file-service/src src
RUN --mount=type=cache,id=cloud-drive-course-maven,target=/root/.m2,sharing=locked sh /usr/local/bin/course-maven-build package

FROM eclipse-temurin:17-jre
WORKDIR /app
COPY --from=build /build/target/file-service.jar app.jar
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
