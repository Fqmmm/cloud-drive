FROM maven:3.9.9-eclipse-temurin-17 AS build
WORKDIR /build
COPY file-service/pom.xml pom.xml
COPY file-service/src src
RUN mvn -B package

FROM eclipse-temurin:17-jre
WORKDIR /app
COPY --from=build /build/target/file-service.jar app.jar
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
